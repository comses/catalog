import enum
import logging
from pprint import pformat

import pandas as pd
from django.db.models import QuerySet
from django_pandas.io import read_frame

from catalog.core.search_indexes import PublicationDocSearch
from citation.models import Publication, Author, PublicationAuthors, Platform, PublicationPlatforms, Sponsor, \
    PublicationSponsors, Tag, PublicationTags, Container, CodeArchiveUrl

logger = logging.getLogger('data_access')


def create_publication_queryset():
    return Publication.api.primary().reviewed() \
        .select_related('container') \
        .prefetch_related('model_documentation') \
        .has_available_code()


def create_publication_df(publication_queryset):
    def _publication_as_dict(p: Publication):
        model_documentation = set(d.name for d in p.model_documentation.all())
        return {'id': p.id,
                'container': p.container.id,
                'date_published': p.date_published,
                'year_published':
                    p.date_published.year if p.date_published is not None else None,
                'has_available_code': p.has_available_code,
                'has_flow_charts': 'Flow charts' in model_documentation,
                'has_math_description': 'Mathematical description' in model_documentation,
                'has_odd': 'ODD' in model_documentation,
                'has_pseudocode': 'Pseudocode' in model_documentation,
                'status': p.status,
                'title': p.title}

    return pd.DataFrame.from_records((_publication_as_dict(p) for p in publication_queryset), index='id')


def create_archive_url_df(publication_queryset):
    def _code_archive_url_as_dict(c: CodeArchiveUrl):
        return {
            'publication__id': c.publication_id,
            'id': c.id,
            'category': str(c.category.category),
            'subcategory': str(c.category.subcategory),
            'available': c.status == 'available'
        }

    return pd.DataFrame.from_records(
        (_code_archive_url_as_dict(c) for c in
         CodeArchiveUrl.objects.filter(publication__in=publication_queryset).select_related('category')),
        index='publication__id',)


def create_publication_author_df(publication_queryset):
    def _publication_author_as_dict(pa: PublicationAuthors):
        return {
            'publication__id': pa.publication_id,
            'related__id': pa.author_id,
            'name': pa.author.name
        }

    return pd.DataFrame.from_records(
        (_publication_author_as_dict(pa) for pa in
         PublicationAuthors.objects.filter(publication__in=publication_queryset).select_related('author')),
        index='publication__id')


def create_publication_container_df(publication_queryset):
    def _container_as_dict(c: Container):
        return {
            'id': c.id,
            'name': c.name
        }

    return pd.DataFrame.from_records(
        (_container_as_dict(c) for c in
         Container.objects.filter(publications__in=publication_queryset).distinct()),
        index='id'
    )


def create_publication_platform_df(publication_queryset):
    publication_platforms = read_frame(
        PublicationPlatforms.objects.filter(publication__in=publication_queryset),
        fieldnames=['publication__id', 'platform__id', 'platform__name'], index_col='publication__id')
    publication_platforms.rename(
        columns={'platform__name': 'name', 'platform__id': 'related__id'}, inplace=True)
    return publication_platforms


def create_publication_sponsor_df(publication_queryset):
    publication_sponsors = read_frame(
        PublicationSponsors.objects.filter(publication__in=publication_queryset),
        fieldnames=['publication__id', 'sponsor__id', 'sponsor__name'], index_col='publication__id')
    publication_sponsors.rename(
        columns={'sponsor__name': 'name', 'sponsor__id': 'related__id'}, inplace=True)
    return publication_sponsors


def build_cache():
    publication_queryset = create_publication_queryset()
    publications = create_publication_df(publication_queryset)
    return {
        'authors': create_publication_author_df(publication_queryset),
        'code_archive_urls': create_archive_url_df(publication_queryset),
        'containers': create_publication_sponsor_df(publication_queryset),
        'platforms': create_publication_platform_df(publication_queryset),
        'publications': publications,
        'sponsors': create_publication_sponsor_df(publication_queryset)
    }


def get_publication_pks_matching_search_criteria(query, facet_filters):
    return [p.id for p in
            PublicationDocSearch().find(q=query, facet_filters=facet_filters).source(['id']).scan()]
