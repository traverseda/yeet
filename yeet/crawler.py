import persistqueue
import asyncio
from playwright.async_api import Request, async_playwright
from pathlib import Path
from loguru import logger
from collections import defaultdict
import time
from urllib.parse import urlparse, urldefrag
import urllib.robotparser
import functools
from contextlib import contextmanager
from typing import List, Optional
import shutil
import re
import itertools
from rich.progress import Progress
from rich.console import Console
import sys
from yeet.warcdb import CrawlInfo, Record
import json

console = Console(color_system=None, stderr=None)

playwright = async_playwright()


class Crawler:
    def __init__(self,
                 urls: List[str],
                 ignore_robots:bool = False,
                 headless:bool = True,
                 queue:Path = Path("./yeet-queue"),
                 max_delay: float =30.0,
                 min_delay: float =0.0,
                 #Filters
                 recursive: bool = False,
                 accept_regex:str=".*",
                 reject_regex:str="a^",
                 prefix_filter:bool = True,
                 accept_prefixes: List[str] = list(),
                 reject_prefixes: List[str] = list(),

                 ):
        self.ignore_robots=ignore_robots
        self.prefix_filter=prefix_filter
        self.headless=headless
        self.accept_prefixes=accept_prefixes
        self.implied_accept_prefixes=[]
        self.reject_prefixes=reject_prefixes
        self.recursive=recursive
        self.min_delay=min_delay
        self.max_delay=max_delay
        self.accept_regex=re.compile(accept_regex)
        self.reject_regex=re.compile(reject_regex)

        self.session = CrawlInfo.create()

        self.queue=persistqueue.UniqueAckQ(queue, auto_commit=True)

        #This simply says the last time a domain was crawled. We can use this to support

        # things like crawl delays.
        self.lastrun = defaultdict(lambda:-10000000000.0)

        #What user agent to respect for robots.txt. We use googlebot as many site
        # admin will do dumb things and we want to get practical robots.txt data.
        self.robot="Googlebot"

        for url in urls:
            urlparts = urlparse(url)
            self.implied_accept_prefixes.append(f"{urlparts.netloc}{urlparts.path}")
            self.add(url)
        logger.info(f"Allowed Prefixs {self.accept_prefixes}, {self.implied_accept_prefixes}")

    def _filter_from_cli_args(self, url):
        urlparts = urlparse(url)
        path = urlparts.netloc+urlparts.path

        if self.prefix_filter:
            prefix_valid=False
            for prefix in itertools.chain(self.accept_prefixes, self.implied_accept_prefixes):
                if path.startswith(prefix):
                    prefix_valid=True

            if not prefix_valid:
                logger.trace(f"Reject {path} since it doesn't start with an acceptable prefix")
                return False

        if path in self.reject_prefixes:
            logger.trace(f"reject {url} since it starts with a reject_prefix")
            return False

        if not self.accept_regex.match(url):
            logger.trace(f"Reject {url} since our accept regex doesn't match it")
            return False

        if self.reject_regex.match(url):
            logger.trace(f"Reject {url} since our reject regex matches it")
            return False

        return True

    def add(self,url):
        logger.info(f"adding {url} to queue")
        self.queue.put(url)



    async def handle_request_finished(self,request: Request):
        logger.info(f"Saving {request} to warcdb")
        response= await request.response()
        if not response:
            raise Exception("No response for request")
        Record.create(
                url=response.url,
                crawl=self.session,
                request_headers=json.dumps(await request.all_headers()),
                request_method=request.method,
                request_post_data=request.post_data,
                request_redirected_from=request.redirected_from,
                response_headers=json.dumps(await response.all_headers()),
                response_body=await response.body(),
                response_status=response.status,
                response_status_text=response.status_text,
                )
        print(request)

    @contextmanager
    def _nack_on_fail(self, item):
        """Add the item back into the queue if it fails for some reason.
        """
        self.queue.ack(item)
        try:
            yield
        except Exception as e:
            logger.exception(f"{item} failed with {e}")
            self.queue.nack(item)

    @functools.lru_cache()
    def _robots_txt(self, domain: str):
        #ToDo: Some assholes block the python user agent even for pages like robots.txt,
        # we need to open the robots.txt page in the browser I suppose.
        # Not a high priority right now, as I'm just trying to get reasonable robots.txt
        # to work respectfully

        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.set_url(f"http://{domain}/robots.txt")
            rp.read()
            logger.info(f"Read robots.txt from http://{domain}/robots.txt")
        except:
            logger.info(f"Couldn't find robots.txt at `http://{domain}/robots.txt`")
        return rp

    async def run(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch_persistent_context(
                "./browserInstance",
                headless=self.headless,
            #args=[
            #    f"--disable-extensions-except={path_to_extension}",
            #    f"--load-extension={path_to_extension}",
            #],
        )
        self.browser.on("requestfinished", self.handle_request_finished )
        with Progress(console=console) as progress:
            queue_progress = progress.add_task("[red]Downloading...")
            while self.queue.size:
                item = self.queue.get()
                await self.crawl(item)
                progress.update(queue_progress, total=self.queue.total+self.queue.acked_count(), completed=self.queue.acked_count())


        shutil.rmtree(self.queue.path)

    async def crawl(self, item):
        with self._nack_on_fail(item):
            if not self.browser:
                raise Exception("Can't find browser context, did you schedule this to run using the run method?")

            domain = urlparse(item).netloc 
            rp = self._robots_txt(domain)

            #Get crawl delay as reported by robots.txt on the site
            crawl_delay = rp.crawl_delay(self.robot) or 0
            crawl_delay = min(self.max_delay,crawl_delay)
            crawl_delay = max(self.min_delay,crawl_delay)

            if not rp.can_fetch(self.robot,item) and self.ignore_robots==False:
                logger.warning(f"site robots.txt dissallows access to {item}, skipping. Run this script with `--ignore-robots` to proceed anyway")
                return

            self.lastrun[domain]=time.monotonic()
            page = await self.browser.new_page()
            await page.goto(item)
            #We do this in javascript land as it normalizes all our links. Just getting the
            # href attribute of an element will often return relative links, then we need to normalize those
            # while taking into account that pages can change their base. Better to let the browser engine
            # handle it.
            if self.recursive:
                links = await page.locator("a").evaluate_all("links => links.map(function(link){return link.href})")
                links = {urldefrag(url)[0] for url in links} #Filter out url fragments and deduplicate list
                links = filter(self._filter_from_cli_args,links)
                list(map(self.add,links))

                print(*links)
            await page.close()


import typer
app = typer.Typer()

@app.command()
@functools.wraps(Crawler)
def crawl(*args,**kwargs):
    crawler=Crawler(*args,**kwargs)
    asyncio.run(crawler.run())

if __name__ == "__main__":
    logger.remove()
    logger.add(lambda m: console.print(m, end=""), colorize=sys.stderr.isatty())
    app()


