import typer
from functools import wraps
from asyncio import run as aiorun
from loguru import logger
from yeet.crawler import Crawler, sessiondir
from typing import List
from pathlib import Path

app = typer.Typer()

async def crawl(
            urls: List[str],
            level: int = 0,
            span_hosts: bool=False,
            #recursive: bool=False,
            no_parent: bool=True,
        #    resumable: bool=True
        ):

    crawler = Crawler(
                level=level
            )
    for item in urls:
        crawler.add(item)
    await crawler.run()

@app.command()
@wraps(crawl)
def crawl_sync(*args,**kwargs):
    """Crawl synchronously
    """
    aiorun(crawl(*args,**kwargs))

@app.command()
@logger.catch
def clear():
    """Clear all crawl queues
    """
    logger.info(f"Searching for sessions in {sessiondir}")
    for item in sessiondir.iterdir():
        item.unlink()
        logger.info(f"Removed session file {item.name}")
    logger.info("Cleared all sessions")

@app.command()
def sessions():
    print(f"Searching for sessions in {sessiondir}")
    print(" -- ".join(('session               ','qsize','unacked','acked','ready','failed')))
    for item in sessiondir.iterdir():
        #Feel free to rewrite all of this
        crawler=Crawler(session=item.stem)
        print(" -- ".join([str(i) for i in [
            item.stem,
            crawler.queue.qsize(),
            crawler.queue.unack_count(),
            crawler.queue.acked_count(),
            crawler.queue.ready_count(),
            crawler.queue.ack_failed_count(),
            ]]))
    return sessiondir.iterdir()

@app.command()
def resume():
    """Finish ongoing crawls
    """
    pass

if __name__ == "__main__":
    app()
