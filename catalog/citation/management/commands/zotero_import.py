from datetime import datetime
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from lxml import html
from pyzotero import zotero

from catalog.citation.models import (Author, Publication, Tag, Note, Platform, Sponsor, Container,
                                     ModelDocumentation)
from catalog.citation import models

import json
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

    def add_arguments(self, parser):
        parser.add_argument('--test',
                            default=False,
                            help='used for test cases only')
        parser.add_argument('--group',
                            dest='group_id',
                            default='284000',
                            help='Zotero group id to pull records from')
        parser.add_argument('--collection',
                            dest='collection_id',
                            default=False,
                            help='Zotero collection ID, used to fetch a particular collection within the group')
        parser.add_argument('--outfile',
                            default='zotero_data.json',
                            help='data file to write zotero results to')
        parser.add_argument('--infile',
                            default='',
                            help='data file to read already persisted zotero results from')

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
        if not created:
            logger.debug("found existing user %s", user)
        return user

    def get_creators(self, data):
        creators = []
        for c in data['creators']:
            creator, created = Author.objects.get_or_create(
                family_name=c['lastName'].strip(),
                given_name=c['firstName'].strip())
            if not created:
                logger.debug("found existing creator %s", creator)
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
                    logger.exception("URL %s could not be parsed for publication_id %s", value, item.pk)
            # match for email
            elif sliced_key == 'ema' or sliced_key == 'e-m':
                item.contact_email = value
            # match for docs
            elif sliced_key == 'doc':
                model_documentation = ModelDocumentation.objects.get_or_create(name=value)[0]
                models.PublicationModelDocumentations.objects.create(publication=item,
                                                                     model_documentation=model_documentation)
            # match for platform
            elif sliced_key == 'pla':
                platform = Platform.objects.get_or_create(name=value)[0]
                models.PublicationPlatforms.objects.create(publication=item, platform=platform)
            # match for sponsor
            elif sliced_key == 'spo':
                sponsor = Sponsor.objects.get_or_create(name=value)[0]
                models.PublicationSponsors.objects.create(publication=item, sponsor=sponsor)
            elif key:
                logger.debug("Tag [%s :: %s] was added as is for publication_id %s", key, value, item.pk)
                tag = Tag.objects.get_or_create(name=t['tag'].strip())[0]
                models.PublicationTags.objects.create(publication=item, tag=tag)
            else:
                tag = Tag.objects.get_or_create(name=value)[0]
                models.PublicationTags.objects.create(publication=item, tag=tag)
        try:
            item.save()
        except Exception:
            logger.exception("Exception while saving tags %s %s for publication_id %s", item, item.title, item.pk)
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

    def create_container_article(self, data, meta):
        zotero_key = data['key']
        try:
            article = Publication.objects.get(zotero_key=zotero_key)
            logger.debug("article with key %s already present %s", zotero_key, article)
            return article
        except Publication.DoesNotExist:
            article = Publication()

        article.zotero_key = zotero_key
        article = self.set_common_fields(article, data, meta)
        article.container = Container.objects.get_or_create(
            name=data['publicationTitle'].strip())[0]
        article.pages = data['pages'].strip()
        article.issn = data['ISSN'].strip().strip()
        article.volume = data['volume'].strip()
        article.issue = data['issue'].strip()
        article.series = data['series'].strip()
        article.series_title = data['seriesText'].strip()
        article.series_text = data['seriesTitle'].strip()
        article.doi = data['DOI'].strip()
        article.save()

        models.PublicationAuthors.objects.bulk_create(
            [models.PublicationAuthors(publication=article, author=author) for author in self.get_creators(data)])

        tags = data['tags']
        if not tags:
            # if publication has no zotero tags, mark it as untagged (i.e not reviewed)
            # FIXME: this condition is rarely if ever true. We need to check for the existence of key: value tags
            # instead of just tags in general because the citation import into zotero via the Web of Science already has
            # numerous general tags
            article.status = Publication.Status.UNTAGGED
        else:
            article = self.set_tags(data, article)
            if not article.code_archive_url:
                article.status = Publication.Status.REVIEWED
            else:
                # if code_archive_url exists, check for validity and set appropriate status
                try:
                    response = requests.get(article.code_archive_url)
                    if response.status_code == 200:
                        article.status = Publication.Status.REVIEWED
                    else:
                        article.status = Publication.Status.REVIEWED
                except Exception:
                    logger.exception("Error verifying code archive url %s for publication_id %s",
                                     article.code_archive_url, article.pk)
                    article.status = Publication.Status.REVIEWED
        article.save()
        return article

    def get_raw_note(self, html_text):
        if html_text:
            return html.document_fromstring(html_text).text_content().strip()
        return ''

    def create_note(self, data, meta):
        try:
            return Note.objects.get(zotero_key=data['key'])
        except Note.DoesNotExist:
            note_text = self.get_raw_note(data['note'])
            if note_text:
                return Note.objects.create(zotero_key=data['key'],
                                           text=note_text,
                                           zotero_date_added=data['dateAdded'],
                                           zotero_date_modified=data['dateModified'],
                                           added_by=self.get_user(meta['createdByUser']))

    def process(self, data):
        for item in data:
            publication_type = item['data']['itemType']
            logger.debug("Generating bibliographic entry of type %s for %s", publication_type, item)
            if publication_type == 'journalArticle':
                article = self.create_container_article(item['data'], item['meta'])

                if item['data']['key'] in note_map:
                    note = note_map[item['data']['key']]
                    note.publication = article
                    note.save()
                else:
                    pub_map.update({item['data']['key']: article})
            elif publication_type == 'note':
                note = self.create_note(item['data'], item['meta'])
                if note:
                    if 'parentItem' in item['data']:
                        if item['data']['parentItem'] in pub_map:
                            note.publication = pub_map[item['data']['parentItem']]
                            note.save()
                        else:
                            note_map.update({item['data']['parentItem']: note})
            else:
                logger.error("Unhandled bibliographic entry: %s", item)

    def handle(self, *args, **options):
        zot = zotero.Zotero(options['group_id'], "group", settings.ZOTERO_API_KEY)
        input_data_file = options['infile']
        if input_data_file:
            logger.debug("Loading data from file %s", input_data_file)
            with open(input_data_file, 'r') as infile:
                json_data = json.load(infile)
        elif options['test']:
            json_data = zot.top(limit=5)
        else:
            zot.add_parameters(limit=100)
            logger.info("Importing data from Zotero.")
            if options['collection_id']:
                json_data = zot.everything(zot.collection_items(options['collection_id']))
            else:
                json_data = zot.everything(zot.items())

            output_data_file = options['outfile']
            logger.debug("saving zotero data to disk at %s", output_data_file)
            with open(output_data_file, 'w') as outfile:
                json.dump(json_data, outfile)

        logger.info("Number of publications to import: %d", len(json_data))
        self.process(json_data)
        logger.info("Zotero import completed.")
