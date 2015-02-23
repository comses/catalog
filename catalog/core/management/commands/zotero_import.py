import requests
from datetime import datetime
import re

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog.core.models import (Publication, Creator, JournalArticle, Tag,
    Note, Book, Platform, Sponsor, Journal, STATUS_CHOICES)

first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')

pub_map = {}
note_map = {}

class Command(BaseCommand):
    help = 'Imports data from zotero'

    def convert(self, name):
        s1 = first_cap_re.sub(r'\1_\2', name)
        return all_cap_re.sub(r'\1_\2', s1).upper()

    def get_user(self, meta_data):
        first_name, last_name = meta_data['createdByUser']['name'].strip().split(' ')
        username =  meta_data['createdByUser']['username'].strip()
        user, created = User.objects.get_or_create(username=username,  defaults={'first_name': first_name, 'last_name': last_name })
        return user

    def get_creators(self, data):
        creators = []
        for c in data['creators']:
            creator, created = Creator.objects.get_or_create(creator_type=self.convert(c['creatorType']),
                    first_name=c['firstName'].strip(), last_name=c['lastName'].strip())
            creators.append(creator)
        return creators

    def set_tags(self, data, item):
        for t in data['tags']:
            values = t['tag'].strip().split(': ')
            if len(values) == 2:
                key = values[0].strip()
                value = values[1].strip()
            else:
                key = ''
                value = values[0].strip()

            if key == 'codeurl':
                if value != 'none':
                    item.archived_url = re.search("(?P<url>https?://[^\s]+)", value).group("url")
                    if item.archived_url[-1] == '>':
                        item.archived_url = item.archived_url[:-1]
            elif key == 'email':
                if value != 'none':
                    item.contact_email = value
            elif key == 'docs':
                item.model_docs = value
            elif key == 'platform':
                if value != 'unknown' and value != 'none':
                    platform, created = Platform.objects.get_or_create(name=value)
                    item.platforms.add(platform)
            elif key == 'sponsor' or key == 'sponse':
                if value != 'none':
                    sponsor, created = Sponsor.objects.get_or_create(name=value)
                    item.sponsors.add(sponsor)
            elif key == 'author':
                continue
            else:
                if key:
                    print "Tag with key: "+ key + " value: "+ value
                    tag, created = Tag.objects.get_or_create(value=value, key=key)
                else:
                    tag, created = Tag.objects.get_or_create(value=value)
                item.tags.add(tag)
        item.save()
        return item

    def set_common_fields(self, item, data, meta):
        item.title = data['title'].strip()
        item.abstract = data['abstractNote'].strip()
        item.short_title = data['shortTitle'].strip()
        item.url = data['url'].strip()
        item.date_published_text = data['date'].strip()
        try:
            item.date_published = datetime.strptime(data['date'].strip(), '%b %Y')
        except:
            try:
                item.date_published = datetime.strptime(data['date'].strip(), '%B %Y')
            except:
                try:
                    item.date_published = datetime.strptime(data['date'].strip(), '%b %d %Y')
                except:
                    print "Date: " + item.date_published_text + " Could not be parsed"

        item.date_accessed = data['accessDate'] or datetime.now().date()
        item.archive = data['archive'].strip()
        item.archive_location = data['archiveLocation'].strip()
        item.library_catalog = data['libraryCatalog'].strip()
        item.call_number = data['callNumber'].strip()
        item.rights = data['rights'].strip()
        item.extra = data['extra'].strip()
        item.published_language = data['language'].strip()
        item.date_added = data['dateAdded']
        item.date_modified = data['dateModified']
        item.added_by = self.get_user(meta)
        return item

    def create_journal(self, data, meta):
        item = JournalArticle()
        item = self.set_common_fields(item, data, meta)
        item.journal, created = Journal.objects.get_or_create(name=data['publicationTitle'].strip(),
                defaults={'abbreviation': data['journalAbbreviation'].strip()})
        item.pages = data['pages'].strip()
        item.issn = data['ISSN'].strip().strip()
        item.volume = data['volume'].strip()
        item.issue = data['issue'].strip()
        item.series = data['series'].strip()
        item.series_title = data['seriesText'].strip()
        item.series_text = data['seriesTitle'].strip()
        item.doi = data['DOI'].strip()
        item.save()

        for c in self.get_creators(data):
            item.creators.add(c)

        item = self.set_tags(data, item)

        if item.archived_url:
            response = requests.get(item.archived_url)
            if response.status_code == 200:
                item.status = STATUS_CHOICES.COMPLETE
            else:
                item.status = STATUS_CHOICES.INVALID_URL
        else:
            item.status = STATUS_CHOICES.INCOMPLETE

        item.save()
        return item

    def create_note(self, data, meta):
        item = Note()
        item.note = data['note'].strip()
        item.date_added = data['dateAdded']
        item.date_modified = data['dateModified']
        item.added_by = self.get_user(meta)
        item.save()
        item = self.set_tags(data, item)
        return item

    def create_book(self, data, meta):
        item = Book()
        item = self.set_common_fields(item, data, meta)
        item.edition = data['edition'].strip()
        item.num_of_pages = data['numPages'].strip()
        item.num_of_volume = data['numberOfVolumes'].strip()
        item.place = data['place'].strip()
        item.publisher = data['publisher'].strip()
        item.volume = data['volume'].strip()
        item.series = data['series'].strip()
        item.series_numner = data['seriesNumber'].strip()
        item.added_by = self.get_user(meta)
        item.save()
        for c in self.get_creators(data):
            item.creators.add(c)
        item = self.set_tags(data, item)
        return item

    def generate_entry(self, data):
        for item in data:
            if item['data']['itemType'] == 'journalArticle':
                article = self.create_journal(item['data'], item['meta'])
                if note_map.has_key(item['data']['key']):
                    note = note_map[item['data']['key']]
                    note.publication = article
                    note.save()
                else:
                    pub_map.update({item['data']['key']: article})
            elif item['data']['itemType'] == 'book':
                pub_map.update({item['data']['key']: self.create_book(item['data'], item['meta'])})
            elif item['data']['itemType'] == 'note':
                note = self.create_note(item['data'], item['meta'])
                if item['data'].has_key('parentItem'):
                    if pub_map.has_key(item['data']['parentItem']):
                        note.publication = pub_map[item['data']['parentItem']]
                        note.save()
                    else:
                        note_map.update({item['data']['parentItem']: note})

    def handle(self, *args, **options):
        start = 0
        while True:
            r = requests.get('https://api.zotero.org/groups/284000/items?v=3&limit=100&start='+ str(start))
            items = len(r.json())
            if items == 0:
                break
            start += items
            self.generate_entry(r.json())
