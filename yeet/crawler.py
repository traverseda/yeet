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
import collections
import typing
from typing import Optional, List
from yeet.crawlerExtention import BaseCrawlerExtention

datadir = Path(user_data_dir("yeet", "OutsideContextSolutions"))
sessiondir = (datadir/"sessions")
sessiondir.mkdir(parents=True, exist_ok=True)

class CustomQueue(persistqueue.UniqueAckQ):
    _TABLE_NAME = 'ack_unique_queue'
    _SQL_CREATE = (
        'CREATE TABLE IF NOT EXISTS {table_name} ('
        '{key_column} INTEGER PRIMARY KEY AUTOINCREMENT, '
        'data BLOB, timestamp FLOAT, status INTEGER, depth INTEGER, UNIQUE (data))'
    )
    def clear_acked_data(*args,**kwargs):
        raise NotImplementedError("We use the ack data to "
                "deduplicate the queue, it can't be removed")
    def task_done(*args,**kwargs):
        raise NotImplementedError("We use the task data to deduplicate"
                "the queue. Instead use `queue.ack()`")

class Crawler(BaseCrawlerExtention):
    def __init__(self,
                session: Optional[str] = None,
                level: int = 1,
                allowed_hosts: Optional[List[str]] =  None,
                allow_all_hosts: bool = False,
                allowed_roots: Optional[List[str]] = None,
            ):

        self.allowed_hosts = allowed_hosts or []

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
        self.sessionData = persistqueue.PDict(sessiondir.as_posix(),self.session+".sqlite")
        super().__init__()

    def add(self,url):
        item = self.queue.put(url)
        if item:
            logger.info(f"Added to queue: `{url}`")
        else:
            logger.debug(f"Duplicate queue item ignored: `{url}`")

    async def get_browser(self):
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.firefox.launch()
        return self.browser


    async def process_item(self, url):
        """Skip the queue and directly process a url
        """
        logger.info(f"Crawling `{url}`")
        browser = await self.get_browser()
        page = await browser.new_page()
        await page.goto(url)

        #Handle the base element for relative urls
        base = await page.query_selector('base')
        if base:
            base = await base.get_attribute('href')
        else:
            base = url

        #Get the current protocol for dynamic protocol links
        protocol, _ = url.split("://")

        links = set()
        #ToDO, automatically click on all url fragments?
        fragments = set()
        
        for item in await page.query_selector_all("a"):
            href = await item.get_attribute("href")
            if not href: continue #Skip missing hrefs

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

        logger.debug(f"Found {len(links)} links at `{url}`")

    async def run(self):
        while self.queue.active_size():
            item = self.queue.get()
            try:
                await self.process_item(item)
                self.queue.ack(item)
            except Exception as e:
                #ToDo, proper falloff for failed item and all that fun stuff
                logger.warning(f"Item failed with `{e}` at `{item}`")
                self.failcounter.update({item,})
                failcount = self.failcounter[item]
                if failcount > 5:
                    logger.warning(f"item failed {failcount} times, aborting `{item}`")
                    self.queue.ack_failed(item)
                else:
                    self.queue.nack(item)
        
        logger.info(f"Queue empty, shutting down `{self}`")
        if self.failcounter:
            logger.warning(f"Session {self.session} had following failures {self.failcounter.keys()}")
        logger.info(f"Removing finished session `{self.session}` at `{self.sessionfile}`")
        del self.queue
        self.sessionfile.unlink()
