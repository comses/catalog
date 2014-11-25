import requests
import datetime
import re

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog.core.models import Publication, Creator, JournalArticle, Tag, Note

first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')

class Command(BaseCommand):
    help = 'Imports data from zotero'

    def convert(self, name):
        s1 = first_cap_re.sub(r'\1_\2', name)
        return all_cap_re.sub(r'\1_\2', s1).upper()

    def get_user(self, meta_data):
        first_name, last_name = meta_data['createdByUser']['name'].split(' ')
        username =  meta_data['createdByUser']['username']
        user, created = User.objects.get_or_create(username=username,  defaults={'first_name': first_name, 'last_name': last_name })
        return user

    def get_creators(self, data):
        creators = []
        for c in data['creators']:
            creator, created = Creator.objects.get_or_create(creator_type=self.convert(c['creatorType']),
                    first_name=c['firstName'], last_name=c['lastName'])
            creators.append(creator)
        return creators

    def get_tags(self, data):
        tags = []
        for t in data['tags']:
            values = t['tag'].split(': ')
            if len(values) == 2:
                tag, created = Tag.objects.get_or_create(name=values[1], tag_type=values[0])
            else:
                tag, created = Tag.objects.get_or_create(name=values[0])
            tags.append(tag)
        return tags

    def create_journal(self, data, meta):
        item = JournalArticle()
        item.title = data['title']
        item.abstract = data['abstractNote']
        item.short_title = data['shortTitle']
        item.url = data['url']
        item.date_published = data['date']
        item.date_accessed = data['accessDate'] or datetime.datetime.now()
        item.archive = data['archive']
        item.archive_location = data['archiveLocation']
        item.library_catalog = data['libraryCatalog']
        item.call_number = data['callNumber']
        item.rights = data['rights']
        item.extra = data['extra']
        item.published_language = data['language']
        item.date_added = data['dateAdded']
        item.date_modified = data['dateModified']
        item.publication_title = data['publicationTitle']
        item.pages = data['pages']
        item.issn = data['ISSN']
        item.volume = data['volume']
        item.issue = data['issue']
        item.series = data['series']
        item.series_title = data['seriesText']
        item.series_text = data['seriesTitle']
        item.journal_abbr= data['journalAbbreviation']
        item.doi = data['DOI']
        item.added_by = self.get_user(meta)
        item.save()

        for c in self.get_creators(data):
            item.creators.add(c)
        for t in self.get_tags(data):
            item.tags.add(t)
        item.save()

    def create_note(self, data, meta):
        item = Note()
        item.note = data['note']
        item.date_added = data['dateAdded']
        item.date_modified = data['dateModified']
        item.added_by = self.get_user(meta)
        item.save()
        for t in self.get_tags(data):
            item.tags.add(t)
        item.save()

    def create_book(seld, data, meta):
        item = Book()
        item.title = data['title']
        item.abstract = data['abstractNote']
        item.short_title = data['shortTitle']
        item.url = data['url']
        item.date_published = data['date']
        item.date_accessed = data['accessDate'] or datetime.datetime.now()
        item.archive = data['archive']
        item.archive_location = data['archiveLocation']
        item.library_catalog = data['libraryCatalog']
        item.call_number = data['callNumber']
        item.rights = data['rights']
        item.extra = data['extra']
        item.published_language = data['language']
        item.date_added = data['dateAdded']
        item.date_modified = data['dateModified']
        item.edition = data['edition']
        item.num_of_pages = data['numPages']
        item.num_of_volume = data['numberOfVolumes']
        item.place = data['place']
        item.publisher = data['publisher']
        item.volume = data['volume']
        item.series = data['series']
        item.series_numner = data['seriesNumber']
        item.added_by = self.get_user(meta)
        item.save()
        for c in self.get_creators(data):
            item.creators.add(c)
        for t in self.get_tags(data):
            item.tags.add(t)
        item.save()


    def generate_entry(self, data):
        for item in data:
            print item['data']['itemType'] + "key: " + item['data']['key']
            if item['data']['itemType'] == 'journalArticle':
                self.create_journal(item['data'], item['meta'])
            elif item['data']['itemType'] == 'book':
                self.create_book(item['data'], item['meta'])
            elif item['data']['itemType'] == 'note':
                note = self.create_note(item['data'], item['meta'])
                if 'parentItem' in item['data'].keys():
                    print "Parent Key: " + item['data']['parentItem']

    def handle(self, *args, **options):
        r = requests.get('https://api.zotero.org/groups/284000/items?v=3&limit=100')
        items = len(r.json())
        sum = items
        self.generate_entry(r.json())

        while items != 0:
            r = requests.get('https://api.zotero.org/groups/284000/items?v=3&limit=100&start='+ str(sum))
            items = len(r.json())
            sum += items
            self.generate_entry(r.json())
