from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from datetime import datetime
from optparse import make_option
from pyzotero import zotero

from catalog.core.models import (Creator, Publication, JournalArticle, Tag, Note, Platform, Sponsor, Journal, ModelDocumentation)

import requests
import re


first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')

pub_map = {}
note_map = {}

class Command(BaseCommand):
    help = 'Imports data from zotero'

    option_list = BaseCommand.option_list + (
        make_option('--test',
            action='store',
            dest='test',
            default=False,
            help='used for test cases only'),
        )

    option_list = option_list + (
        make_option('--group',
            action='store',
            dest='group_id',
            default='284000',
            help='zotero group id'),
        )


    def convert(self, name):
        s1 = first_cap_re.sub(r'\1_\2', name)
        return all_cap_re.sub(r'\1_\2', s1).upper()

    def get_user(self, meta_data):
        first_name, last_name = meta_data['createdByUser']['name'].strip().split(' ')
        username =  meta_data['createdByUser']['username'].strip()
        user, created = User.objects.get_or_create(username=username, defaults={'first_name': first_name, 'last_name': last_name })
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
                key = values[0].strip().lower()
                value = values[1].strip()
            else:
                key = ''
                value = values[0].strip()

            if key == 'codeurl':
                if value != 'none':
                    try:
                        item.code_archive_url = re.search("(?P<url>https?://[^\s]+)", value).group("url")
                        if item.code_archive_url[-1] == '>':
                            item.code_archive_url = item.code_archive_url[:-1]
                    except:
                        print "URL: " + value + " could not parsed"
            elif key == 'email' or key == 'e-mail':
                if value != 'none':
                    item.contact_email = value
            elif key == 'docs':
                item.model_documentation, created = ModelDocumentation.objects.get_or_create(value=value)
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
                    print "Tag with key: "+ key + " value: "+ value + " was added as it is."
                    tag, created = Tag.objects.get_or_create(value=t)
                else:
                    tag, created = Tag.objects.get_or_create(value=value)
                item.tags.add(tag)
        try:
            item.save()
        except Exception as e:
            print "Exception "+ str(e) + " in saving tags: " + str(item) + str(item.title)
        return item

    def parse_published_date(self, date):
        try:
            return datetime.strptime(date, '%b %Y')
        except:
            try:
                return datetime.strptime(date, '%B %Y')
            except:
                try:
                    return datetime.strptime(date, '%b %d %Y')
                except:
                    try:
                        return datetime.strptime(date, '%Y')
                    except:
                        year = re.findall('\\b\\d+\\b', date)
                        if year:
                            return datetime(int(year[-1]), 1, 1)
                        else:
                            print "Date: " + item.date_published_text + " Could not be parsed"
                            return None

    def set_common_fields(self, item, data, meta):
        item.title = data['title'].strip()
        item.abstract = data['abstractNote'].strip()
        item.short_title = data['shortTitle'].strip()
        item.url = data['url'].strip()
        item.date_published_text = data['date'].strip()
        item.date_published = self.parse_published_date(data['date'].strip())
        item.date_accessed = data['accessDate'].strip() or datetime.now().date()
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

    def create_journal_article(self, data, meta):
        try:
            return JournalArticle.objects.get(zotero_key=data['key'])
        except JournalArticle.DoesNotExist:
            item = JournalArticle(zotero_key=data['key'])

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

        if item.code_archive_url:
            try:
                response = requests.get(item.code_archive_url)
                if response.status_code == 200:
                    item.status = Publication.STATUS_CHOICES.COMPLETE
                else:
                    item.status = Publication.STATUS_CHOICES.INVALID_URL
            except Exception as e:
                print "Error verifying code archive url" + str(e)
                item.status = Publication.STATUS_CHOICES.INCOMPLETE
        else:
            item.status = Publication.STATUS_CHOICES.INCOMPLETE

        item.save()
        return item

    def create_note(self, data, meta):
        try:
            return Note.objects.get(zotero_key=data['key'])
        except Note.DoesNotExist:
            item = Note(zotero_key=data['key'])
        item.text = data['note'].strip()
        item.date_added = data['dateAdded']
        item.date_modified = data['dateModified']
        item.added_by = self.get_user(meta)
        item.save()
        item = self.set_tags(data, item)
        return item

    def generate_entry(self, data):
        for item in data:
            if item['data']['itemType'] == 'journalArticle':
                article = self.create_journal_article(item['data'], item['meta'])

                if note_map.has_key(item['data']['key']):
                    note = note_map[item['data']['key']]
                    note.publication = article
                    note.save()
                else:
                    pub_map.update({item['data']['key']: article})
            elif item['data']['itemType'] == 'note':
                note = self.create_note(item['data'], item['meta'])
                if item['data'].has_key('parentItem'):
                    if pub_map.has_key(item['data']['parentItem']):
                        note.publication = pub_map[item['data']['parentItem']]
                        note.save()
                    else:
                        note_map.update({item['data']['parentItem']: note})

    def handle(self, *args, **options):

        if settings.ZOTERO_API_KEY:
            zot = zotero.Zotero(options['group_id'], "group", settings.ZOTERO_API_KEY)

        print "Starting to import data from Zotero. Hang tight, this may take a while."
        if options['test']:
            json_data = zot.top(limit=5)
        else:
            json_data = zot.all_top()

        print "Number of Publications to import: " + str(len(json_data))
        self.generate_entry(json_data)
        print "Import from Zotero is finished."
