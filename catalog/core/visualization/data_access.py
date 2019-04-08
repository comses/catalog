import logging

import pandas as pd
from django.core.cache import cache
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
                'container_id': p.container.id,
                'container_name': p.container.name,
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
            'publication_id': c.publication_id,
            'code_archive_url_id': c.id,
            'category': str(c.category.category),
            'subcategory': str(c.category.subcategory),
            'available': c.status == 'available'
        }

    df = pd.DataFrame.from_records(
        (_code_archive_url_as_dict(c) for c in
         CodeArchiveUrl.objects.filter(publication__in=publication_queryset).select_related('category')),
        index='publication_id')
    df['category'] = df['category'].astype('category')
    df['subcategory'] = df['subcategory'].astype('category')
    return df


def create_publication_author_df(publication_queryset):
    def _publication_author_as_dict(pa: PublicationAuthors):
        return {
            'publication_id': pa.publication_id,
            'author_id': pa.author_id,
            'name': pa.author.name
        }

    return pd.DataFrame.from_records(
        (_publication_author_as_dict(pa) for pa in
         PublicationAuthors.objects.filter(publication__in=publication_queryset).select_related('author')),
        index='publication_id')


def create_publication_platform_df(publication_queryset):
    publication_platforms = read_frame(
        PublicationPlatforms.objects.filter(publication__in=publication_queryset),
        fieldnames=['publication__id', 'platform__id', 'platform__name'], index_col='publication__id') \
        .rename(columns={'platform__id': 'platform_id', 'platform__name': 'platform_name'})
    return publication_platforms


def create_publication_sponsor_df(publication_queryset):
    publication_sponsors = read_frame(
        PublicationSponsors.objects.filter(publication__in=publication_queryset),
        fieldnames=['publication__id', 'sponsor__id', 'sponsor__name'], index_col='publication__id') \
        .rename(columns={'sponsor__id': 'sponsor_id', 'sponsor__name': 'sponsor_name'})
    return publication_sponsors


class VisualizationCache:
    CREATE_RELATED_DF = {
        'authors': create_publication_author_df,
        'code_archive_urls': create_archive_url_df,
        'platforms': create_publication_platform_df,
        'publications': create_publication_df,
        'sponsors': create_publication_sponsor_df
    }

    def get_related(self, key):
        related_df = cache.get(key, None)
        return related_df

    def set_related(self, key, publication_queryset):
        logger.info('preparing to cache %s', key)
        create_related_df = self.CREATE_RELATED_DF[key]
        related_df = create_related_df(publication_queryset)
        self.set(key, related_df)
        logger.info('cached %s', key)
        return related_df

    def set(self, key, related_df):
        return cache.set(key, related_df)

    def get_publications(self):
        return self.get_or_create_many({'publications',})['publications']

    def get_or_create_many(self, keys=None):
        publication_queryset = create_publication_queryset()
        if keys is None:
            keys = {'authors', 'code_archive_urls', 'platforms', 'publications', 'sponsors'}
        results = cache.get_many(keys)
        missing_keys = keys.difference(results.keys())
        logger.info("missing_keys: %s", missing_keys)
        for key in sorted(missing_keys):
            results[key] = self.set_related(key, publication_queryset)
        return results


def get_publication_pks_matching_search_criteria(query, facet_filters):
    return [p.id for p in
            PublicationDocSearch().find(q=query, facet_filters=facet_filters).source(['id']).scan()]


visualization_cache = VisualizationCache()
