import enum
import logging

import pandas as pd
from django.db.models import QuerySet
from django_pandas.io import read_frame

from catalog.core.search_indexes import PublicationDocSearch
from citation.models import Publication, Author, PublicationAuthors, Platform, PublicationPlatforms, Sponsor, \
    PublicationSponsors, Tag, PublicationTags, Container

logger = logging.getLogger('data_access')


class IncludedStatistics(enum.Enum):
    code_availability_count = 'Code Availability Count'
    odd_count = 'ODD Documentation Count'
    formal_description_count = 'Formal Description Count'
    visual_documentation_count = 'Visual Documentation Count'

    @classmethod
    def levels(cls):
        return [cls.code_availability_count,
                cls.odd_count,
                cls.formal_description_count,
                cls.visual_documentation_count]

    @classmethod
    def names(cls):
        if not hasattr(cls, '_names'):
            cls._names = [l.name for l in cls.levels()]
        return cls._names

    @classmethod
    def labels(cls):
        if not hasattr(cls, '_levels'):
            cls._levels = [l.value for l in cls.levels()]
        return cls._levels

    @classmethod
    def styles(cls):
        if not hasattr(cls, '_styles'):
            cls._styles = ['dashed', 'dotted', '10 2', '2 10']
        return cls._styles


class SearchMixin:
    def get_full_text_matches(self, query, facet_filters):
        publication_ids = [p.id for p in
                           PublicationDocSearch().find(q=query, facet_filters=facet_filters).source(['id']).scan()]
        publication_matches = self.data_cache.publications.loc[publication_ids]
        return publication_matches

    def get_related_names(self, related_ids):
        related_table = getattr(self.data_cache, self.related_name)
        return related_table.loc[related_ids]


class ManyToManyModelDataAccess(SearchMixin):
    def __init__(self, data_cache: 'DataCache', related_name, related_through_name):
        self.data_cache = data_cache
        self.related_name = related_name
        self.related_through_name = related_through_name

    def get_year_related_counts(self, df: pd.DataFrame, related_ids):
        related_through_table = getattr(self.data_cache, self.related_through_name)
        related = related_through_table[related_through_table.related__id.isin(related_ids)]
        _counts_df = df.join(related, how='inner').groupby(['year_published', 'related__id']).agg(
            dict(title='count', is_archived='sum',
                 has_formal_description='sum', has_odd='sum', has_visual_documentation='sum'))
        mi = self.data_cache.get_all_year_related_combinations(related_ids)
        counts_df = _counts_df.reindex(mi, fill_value=0)
        return counts_df.rename(columns={
            'title': 'count',
            'is_archived': IncludedStatistics.code_availability_count.name,
            'has_formal_description': IncludedStatistics.formal_description_count.name,
            'has_odd': IncludedStatistics.odd_count.name,
            'has_visual_documentation': IncludedStatistics.visual_documentation_count.name
        })


class JournalDataAccess(SearchMixin):
    related_name = 'container'

    def __init__(self, data_cache: 'DataCache'):
        self.data_cache = data_cache

    def get_year_related_counts(self, df: pd.DataFrame, related_ids):
        renames = {
            'title': 'count',
            'is_archived': IncludedStatistics.code_availability_count.name,
            'has_formal_description': IncludedStatistics.formal_description_count.name,
            'has_odd': IncludedStatistics.odd_count.name,
            'has_visual_documentation': IncludedStatistics.visual_documentation_count.name
        }
        counts_df = df[df.container.isin(related_ids)] \
            .rename(columns={'container': 'related__id'}) \
            .groupby(['year_published', 'related__id']) \
            .agg(dict(title='count', is_archived='sum',
                      has_formal_description='sum', has_odd='sum', has_visual_documentation='sum'))
        counts_df = counts_df.rename(columns=renames)
        # logger.info(counts_df.columns)
        mi = self.data_cache.get_all_year_related_combinations(related_ids)
        return counts_df.reindex(mi, fill_value=0)


class DataCache:
    def __init__(self):
        logger.info('creating shared data cache')
        self._publication_queryset = None
        self._publications = None

        self._authors = None
        self._publication_authors = None

        self._containers = None

        self._platforms = None
        self._publication_platforms = None

        self._sponsors = None
        self._publication_sponsors = None

        self._tags = None
        self._publication_tags = None

    def _publication_as_dict(self, p: Publication):
        model_documentation = set(d.name for d in p.model_documentation.all())
        return {'id': p.id,
                'container': p.container.id,
                'date_published': p.date_published,
                'year_published':
                    p.date_published.year if p.date_published is not None else None,
                'is_archived': p.is_archived,
                'has_odd': 'ODD' in model_documentation,
                'has_visual_documentation': any(
                    d in model_documentation for d in ['UML', 'Flow Charts', 'AORML', 'Ontologies']),
                'has_formal_description': any(
                    d in model_documentation for d in ['Source code', 'Pseudocode', 'Mathematical description']),
                'status': p.status,
                'title': p.title}

    def _author_as_dict(self, a: Author):
        return {
            'id': a.id,
            'name': a.name
        }

    def _container_as_dict(self, c: Container):
        return {
            'id': c.id,
            'name': c.name
        }

    def _publication_author_as_dict(self, pa: PublicationAuthors):
        return {
            'publication__id': pa.publication_id,
            'related__id': pa.author_id,
            'name': pa.author.name
        }

    @property
    def publication_queryset(self) -> QuerySet:
        if self._publication_queryset is None:
            self._publication_queryset = Publication.api.primary().filter(status='REVIEWED') \
                .select_related('container') \
                .prefetch_related('model_documentation')
        return self._publication_queryset

    @property
    def publications(self):
        if self._publications is None:
            self._publications = pd.DataFrame.from_records(
                (self._publication_as_dict(p) for p in self.publication_queryset), index='id')
            self._publications.index.rename(name='publication__id', inplace=True)
        return self._publications

    @property
    def authors(self):
        if self._authors is None:
            self._authors = pd.DataFrame.from_records(
                (self._author_as_dict(a) for a in
                 Author.objects.filter(publications__in=self.publication_queryset).distinct()),
                index='id')
        return self._authors

    @property
    def publication_authors(self):
        if self._publication_authors is None:
            self._publication_authors = pd.DataFrame.from_records(
                (self._publication_author_as_dict(pa) for pa in
                 PublicationAuthors.objects.filter(publication__in=self.publication_queryset).select_related('author')),
                index='publication__id')
        return self._publication_authors

    @property
    def container(self):
        if self._containers is None:
            self._containers = pd.DataFrame.from_records(
                (self._container_as_dict(c) for c in
                Container.objects.filter(publications__in=self.publication_queryset).distinct()),
                index='id'
            )
        return self._containers

    @property
    def platforms(self):
        if self._platforms is None:
            self._platforms = read_frame(Platform.objects.filter(publications__in=self.publication_queryset).distinct(),
                                         fieldnames=['id', 'name'], index_col='id')
        return self._platforms

    @property
    def publication_platforms(self):
        if self._publication_platforms is None:
            self._publication_platforms = read_frame(
                PublicationPlatforms.objects.filter(publication__in=self.publication_queryset),
                fieldnames=['publication__id', 'platform__id', 'platform__name'], index_col='publication__id')
            self._publication_platforms.rename(
                columns={'platform__name': 'name', 'platform__id': 'related__id'}, inplace=True)
        return self._publication_platforms

    @property
    def sponsors(self):
        if self._sponsors is None:
            self._sponsors = read_frame(Sponsor.objects.filter(publications__in=self.publication_queryset).distinct(),
                                        fieldnames=['id', 'name'], index_col='id')
        return self._sponsors

    @property
    def publication_sponsors(self):
        if self._publication_sponsors is None:
            self._publication_sponsors = read_frame(
                PublicationSponsors.objects.filter(publication__in=self.publication_queryset),
                fieldnames=['publication__id', 'sponsor__id', 'sponsor__name'], index_col='publication__id')
            self._publication_sponsors.rename(
                columns={'sponsor__name': 'name', 'sponsor__id': 'related__id'}, inplace=True)
        return self._publication_sponsors

    @property
    def tags(self):
        if self._tags is None:
            self._tags = read_frame(Tag.objects.filter(publications__in=self.publication_queryset).distinct(),
                                    fieldnames=['id', 'name'], index_col='id')
        return self._tags

    @property
    def publication_tags(self):
        if self._publication_tags is None:
            self._publication_tags = read_frame(
                PublicationTags.objects.filter(publication__in=self.publication_queryset),
                fieldnames=['publication__id', 'tag__id', 'tag__name'], index_col='publication__id')
            self._publication_tags.rename(
                columns={'tag__name': 'name', 'tag__id': 'related__id'}, inplace=True)
        return self._publication_tags

    def get_model_data_access_api(self, related_name, related_through_name=None):
        if related_name == JournalDataAccess.related_name:
            return JournalDataAccess(data_cache=self)
        if related_through_name is None:
            related_through_name = 'publication_{}'.format(related_name)
        return ManyToManyModelDataAccess(data_cache=self, related_name=related_name,
                                         related_through_name=related_through_name)

    def get_all_year_related_combinations(self, related_ids):
        return pd.MultiIndex.from_product([range(1995, 2018), related_ids], names=['year_published', 'related__id'])


data_cache = DataCache()
