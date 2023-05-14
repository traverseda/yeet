"""A database schema designed for compatibility with the WARC file format

We're not using real warc for a few reasons, mostly because we'd also need
to maintain a CDX file and at that point why not just through it in sqlite.
"""
from peewee import SmallIntegerField, SqliteDatabase, Model
from peewee import Model, SqliteDatabase, CharField, TextField, BlobField, AutoField, ForeignKeyField, DateTimeField, CompositeKey
import shortuuid
import datetime

database = SqliteDatabase("warcdb.sqlite")

class CrawlInfo(Model):
    session = CharField(primary_key=True, default=shortuuid.uuid)
    crawl_start = DateTimeField(default=datetime.datetime.now)

    class Meta:
        database = database

class Record(Model):
    id = AutoField()
    crawl = ForeignKeyField(CrawlInfo)
    url = TextField()
    time = DateTimeField(default=datetime.datetime.now)

    request_headers = TextField()
    request_method = TextField()
    request_post_data = BlobField(null=True)
    request_redirected_from = ForeignKeyField('self', null=True)
    response_headers = TextField()
    response_body = BlobField(null=True)
    response_status = SmallIntegerField()
    response_status_text = TextField()


    class Meta:
        database = database
#        primary_key = CompositeKey('id', 'crawl')

database.create_tables([CrawlInfo, Record])
