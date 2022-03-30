"""The main crawler
"""
import shortuuid
import persistqueue
from pathlib import Path
import urllib
from appdirs import user_data_dir
from loguru import logger
import asyncio
from playwright.async_api import async_playwright
from urllib.parse import urlparse
import collections
import typing
from typing import Optional, List
from yeet.crawlerExtention import BaseCrawlerExtention

datadir = Path(user_data_dir("yeet", "OutsideContextSolutions"))
sessiondir = (datadir/"sessions")
sessiondir.mkdir(parents=True, exist_ok=True)

class CustomQueue(persistqueue.UniqueAckQ):
    def clear_acked_data(*args,**kwargs):
        raise NotImplementedError("We use the ack data to "
                "deduplicate the queue, it can't be removed")
    def task_done(*args,**kwargs):
        raise NotImplementedError("We use the task data to deduplicate"
                "the queue. Instead use `queue.ack()`")

class PDict(persistqueue.PDict):
    def __init__(self, path, name, multithreading=False,db_file_name=None):
        # PDict is always auto_commit=True
        super(persistqueue.PDict, self).__init__(path, name=name,
                                    multithreading=multithreading,
                                    auto_commit=True,
                                    db_file_name=db_file_name)



class Crawler(BaseCrawlerExtention):
    def __init__(self,
                session: Optional[str] = None,
                level: int = 0,
                allowed_hosts: Optional[List[str]] =  None,
                allow_all_hosts: bool = False,
                allowed_roots: Optional[List[str]] = None,
            ):

        self.allowed_hosts = allowed_hosts or []
        self.level = level
        self.session=session
        if not self.session:
            self.session=shortuuid.uuid()

        self.queue = CustomQueue(
                sessiondir.as_posix(),
                db_file_name=self.session+".sqlite",
                #serializer=persistqueue.serializers.msgpack
            )
        self.sessionfile = sessiondir/f"{self.session}.sqlite"
        assert self.sessionfile.exists()

        self.browser=None
        self.failcounter = collections.Counter()

        #If self.sessiondata exists we load that to get session settings.

        self.sessionData = PDict(sessiondir.as_posix(),
                name='data',
                db_file_name=self.session+".sqlite")
        self.sessionCache = PDict(sessiondir.as_posix(),
                name='cache',
                db_file_name=self.session+".sqlite")

        super().__init__()

    def add_allowed_host(self,url: str):
        domain = urlparse(item[0]).netloc
        self.allowed_hosts.append(domain)
        logger.debug(f"Added {domain} to allowed_domains")

    def add_allowed_root(self,url:str):
        root = urlparse(item[0])
        self.allowed_roots.append(root.netloc+root.path)
        logger.debug(f"Added {root} to allowed_roots")

    def filter_level(self, item):
        return item[1] > self.level

    def filter_allowed_hosts(self,item):
        domain = urlparse(item[0]).netloc
        return domain in allowed_hosts

    def filter_allowed_roots(self,item):
        root = urlparse(item[0])
        return root.netloc+root.path in allowed_paths

    def add(self,item):
        if item[1] > self.level:
            logger.debug(f"ignoring `{item}` as it's too far from our root")
            return
        unique = self.queue.put(item)
        if unique:
            logger.info(f"Added to queue: `{item}`")
        else:
            logger.debug(f"Duplicate queue item ignored: `{item}`")

    async def get_browser(self):
        if not self.browser or not self.browser.is_connected():
            logger.debug("Creating new browser context")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.firefox.launch()
        return self.browser


    async def process_item(self, url, depth):
        """Skip the queue and directly process a url
        """
        if url in self.sessionData:
            logger.debug(f"skipping '{url}' as it's already been collected")
        self.sessionData[url]=True
        logger.info(f"Crawling '{url}'")
        browser = await self.get_browser()
        page = await browser.new_page()
        await page.goto(url)

        #Handle the base element for relative urls
        try:
            base = await page.eval_on_selector('base',
                'elements => elements.map(element => element.href)')
        except Exception as e:
            logger.debug(f"'{e}', setting base to '{url}'")
            base = url

        #Get the current protocol for dynamic protocol links
        protocol, _ = url.split("://")

        links = set()
        #ToDO, automatically click on all url fragments?
        fragments = set()
        
        for href in await page.eval_on_selector_all('a',
                'elements => elements.map(element => element.href)'):
            #Fix dynamic protocol to match current url
            if href.startswith("//"):
                href=protocol+":"+href

            #Fix relative urls by checking is they have a domain set
            if not urllib.parse.urlparse(href).netloc:
                href = urllib.parse.urljoin(base,url)
            
            href, fragment = urllib.parse.urldefrag(href)
            #We don't want to follow fragments in general, but
            # if the fragment points to the current page we
            # may want to click on it later.
            if not href or href == url:
                fragments.add(fragment)
            links.add(href)
        newdepth=depth+1
        for link in links:
            self.add((link,newdepth))
        logger.debug(f"Found {len(links)} links at `{url}`")
        #ToDO this should be running under a context manager...
        await page.close()
        del page

    async def run(self):
        #ToDo: This whole queueing system needs to be updated to better
        # support things like throttling, without sleeping the entire task.
        while self.queue.active_size():
            item = self.queue.get()
            url, depth = item

            #Logorithmic wait on errors
            failcount = self.failcounter[item]
            if failcount:
                await asyncio.sleep(failcount*failcount)

            try:
                await self.process_item(*item)
                self.queue.ack(item)
            except Exception as e:
                self.failcounter.update({item,})
                if failcount > 5:
                    logger.warning(f"item failed {failcount} times, aborting `{item}`")
                    self.queue.ack_failed(item)
                else:
                    logger.warning(f"Item failed with `{e}`, waiting {failcount*failcount} seconds, at `{item}`")
                    del self.sessionData[url]
                    self.queue.nack(item)
        
        logger.info(f"Queue empty, shutting down `{self}`")
        if self.failcounter:
            logger.warning(f"Session {self.session} had following failures {self.failcounter.keys()}")
        logger.info(f"Removing finished session `{self.session}` at `{self.sessionfile}`")
        del self.queue
        del self.sessionData
        del self.sessionCache
        self.sessionfile.unlink()
