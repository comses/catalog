from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from datetime import datetime
from optparse import make_option
from pyzotero import zotero

from catalog.core.models import (Creator, Publication, JournalArticle, Tag, Note, Platform, Sponsor, Journal,
                                 ModelDocumentation)

import logging
import requests
import re


logger = logging.getLogger(__name__)

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
        make_option('--collection',
                    action='store',
                    dest='collection_id',
                    default=False,
                    help='used to fetch a particular collection in the group')
    )

    def convert(self, name):
        s1 = first_cap_re.sub(r'\1_\2', name)
        return all_cap_re.sub(r'\1_\2', s1).upper()

    def get_user(self, user_dict):
        name = user_dict['name']
        username = user_dict['username'].strip()
        first_name, last_name = name.strip().split(' ') if name else ('', '')
        user, created = User.objects.get_or_create(username=username,
                                                   defaults={'first_name': first_name,
                                                             'last_name': last_name})
        return user

    def get_creators(self, data):
        creators = []
        for c in data['creators']:
            creator, created = Creator.objects.get_or_create(
                creator_type=self.convert(c['creatorType']),
                first_name=c['firstName'].strip(), last_name=c['lastName'].strip())
            creators.append(creator)
        return creators

    def get_key_value(self, tag):
        values = tag.split(': ')
        if len(values) == 2:
            return values[0].strip().lower(), values[1].strip()
        else:
            return '', values[0].strip()

    def set_tags(self, data, item):
        for t in data['tags']:
            key, value = self.get_key_value(t['tag'].strip())

            sliced_key = key[:3]
            # match author or unknown or none
            if value == 'unknown' or value == 'none' or sliced_key == 'aut':
                continue

            # match for codeurl
            if sliced_key == 'cod':
                try:
                    item.code_archive_url = re.search("(?P<url>https?://[^\s]+)", value).group("url")
                    if item.code_archive_url[-1] == '>':
                        item.code_archive_url = item.code_archive_url[:-1]
                except Exception:
                    logger.exception("URL %s could not be parsed", value)
            # match for email
            elif sliced_key == 'ema' or sliced_key == 'e-m':
                item.contact_email = value
            # match for docs
            elif sliced_key == 'doc':
                item.model_documentation, created = ModelDocumentation.objects.get_or_create(value=value)
            # match for platform
            elif sliced_key == 'pla':
                platform, created = Platform.objects.get_or_create(name=value)
                item.platforms.add(platform)
            # match for sponsor
            elif sliced_key == 'spo':
                sponsor, created = Sponsor.objects.get_or_create(name=value)
                item.sponsors.add(sponsor)
            elif key:
                logger.debug("Tag [%s :: %s] was added as is.", key, value)
                tag, created = Tag.objects.get_or_create(value=t['tag'].strip())
            else:
                tag, created = Tag.objects.get_or_create(value=value)
                item.tags.add(tag)
        try:
            item.save()
        except Exception:
            logger.exception("Exception while saving tags %s %s", item, item.title)
        return item

    def parse_published_date(self, date):
        try:
            return datetime.strptime(date, '%b %Y')
        except ValueError:
            try:
                return datetime.strptime(date, '%B %Y')
            except ValueError:
                try:
                    return datetime.strptime(date, '%b %d %Y')
                except ValueError:
                    try:
                        return datetime.strptime(date, '%Y')
                    except ValueError:
                        year = re.findall('\\b\\d+\\b', date)
                        if year:
                            return datetime(int(year[-1]), 1, 1)
                        else:
                            logger.error("Could not parse date %s", date)
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
        item.zotero_date_added = data['dateAdded']
        item.zotero_date_modified = data['dateModified']
        item.added_by = self.get_user(meta['createdByUser'])
        return item

    def create_journal_article(self, data, meta):
        try:
            return JournalArticle.objects.get(zotero_key=data['key'])
        except JournalArticle.DoesNotExist:
            item = JournalArticle(zotero_key=data['key'])

        item = self.set_common_fields(item, data, meta)
        item.journal, created = Journal.objects.get_or_create(
            name=data['publicationTitle'].strip(),
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

        # FIXME: we need to add a corner case to distinguish between Status.UNTAGGED and Status.NEEDS_AUTHOR_REVIEW
        if not item.code_archive_url:
            item.status = Publication.Status.NEEDS_AUTHOR_REVIEW
        else:
            # if code_archive_url exists, check for validity and set appropriate status
            try:
                response = requests.get(item.code_archive_url)
                if response.status_code == 200:
                    item.status = Publication.Status.COMPLETE
                else:
                    item.status = Publication.Status.NEEDS_AUTHOR_REVIEW
            except Exception:
                logger.exception("Error verifying code archive url %s", item.code_archive_url)
                item.status = Publication.Status.NEEDS_AUTHOR_REVIEW

        item.save()
        return item

    def create_note(self, data, meta):
        try:
            return Note.objects.get(zotero_key=data['key'])
        except Note.DoesNotExist:
            item = Note(zotero_key=data['key'])
        item.text = data['note'].strip()
        item.zotero_date_added = data['dateAdded']
        item.zotero_date_modified = data['dateModified']
        item.added_by = self.get_user(meta['createdByUser'])
        item.save()
        item = self.set_tags(data, item)
        return item

    def generate_entry(self, data):
        for item in data:
            if item['data']['itemType'] == 'journalArticle':
                article = self.create_journal_article(item['data'], item['meta'])

                if item['data']['key'] in note_map:
                    note = note_map[item['data']['key']]
                    note.publication = article
                    note.save()
                else:
                    pub_map.update({item['data']['key']: article})
            elif item['data']['itemType'] == 'note':
                note = self.create_note(item['data'], item['meta'])

                if 'parentItem' in item['data']:
                    if item['data']['parentItem'] in pub_map:
                        note.publication = pub_map[item['data']['parentItem']]
                        note.save()
                    else:
                        note_map.update({item['data']['parentItem']: note})

    def handle(self, *args, **options):
        zot = zotero.Zotero(options['group_id'], "group", settings.ZOTERO_API_KEY)
        if options['test']:
            json_data = zot.top(limit=5)
        else:
            zot.add_parameters(limit=100)
            logger.info("Starting to import data from Zotero. Hang tight, this may take a while.")
            if options['collection_id']:
                json_data = zot.everything(zot.collection_items(options['collection_id']))
            else:
                json_data = zot.all_top()

        logger.info("Number of Publications to import: %d", len(json_data))
        self.generate_entry(json_data)
        logger.info("Zotero import completed.")
