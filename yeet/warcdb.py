"""A database schema designed for compatibility with the WARC file format

We're not using real warc for a few reasons, mostly because we'd also need
to maintain a CDX file and at that point why not just through it in sqlite.

This file (and this file alone) is licensed under the MIT license instead of yeet's broader AGPL license,
in an effort to provide better interopobility with commercial projects. If there's sufficient interest in splitting
this off into it's own pip package I will, but unless you have an actual project
this like 100+ users probably just copy this file out of the repo.

Copyright 2023 Alex Davies <traverse.da@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

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
