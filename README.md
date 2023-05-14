`yeet` is a generic web crawler using python-playwright using asyncio.

Yeet aims to fill a similar niche as wget.

Features

 * Run javascript during your crawls
 * Easy to extend and customize
 * It also works nicely as a python library, cli commands are thin wrappers around
     actual python functions
 * WARC-like archiving (archive to sqlite file that has similar record structure)

# ToDo

 * We spend most of our time talking to playwright

Since we're using asyncio we should be able to speed that up by running multiple
tasks in paralel, as most of it is waiting for non-blocking IO.

# Notes

Profile performance with py-spy

`LOGURU_LEVEL=INFO poetry run py-spy record -o profile.svg -- python3 yeet/cli.py crawl https://www.wikipedia.org/ --level=1`


