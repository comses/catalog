from typing import Sequence

from bokeh.models import TableColumn, DataTable, ColumnDataSource
from django.db.models import Count
from django_pandas.io import read_frame

from citation.models import Publication


class FieldMeta:
    @classmethod
    def create_db_name_to_name_lookup(cls, collection: Sequence):
        return {fm.db_name: fm.name for fm in collection if fm.db_name != fm.name}


class FieldDBMeta:
    def __init__(self, db_name: str, name: str, title: str):
        self.db_name = db_name
        self.name = name
        self.title = title

    def to_table_column(self):
        return TableColumn(field=self.name, title=self.title)


class FieldAggDBMeta:
    def __init__(self, db_name, db_expr, title):
        self.db_name = db_name
        self.db_expr = db_expr
        self.title = title

    @property
    def name(self):
        return self.db_name

    def to_table_column(self):
        return TableColumn(field=self.name, title=self.title)

    @classmethod
    def create_db_name_to_aggregate_lookup(cls, collection: Sequence['FieldAggDBMeta']):
        return {fm.db_name: fm.db_expr for fm in collection}


def publication_as_dict(p: Publication):
    return {'id': p.id,
            'container': p.container.id,
            'date_published': p.date_published,
            'year_published':
                p.date_published.year if p.date_published is not None else None,
            'flagged': p.flagged,
            'is_archived': p.is_archived,
            'status': p.status,
            'title': p.title}


class CategoryStatistics:
    def __init__(self, grouping_field: FieldDBMeta, statistics=None):
        self.queryset = Publication.api.primary().filter(status='REVIEWED')
        self.grouping_field = grouping_field
        self.statistics = [
            FieldAggDBMeta(db_name='count', db_expr=Count('*'), title='Count')] if not statistics else statistics
        self.order_by = '-count'

    def create_top_10_table(self):
        qs = self.queryset.values(self.grouping_field.db_name) \
                 .annotate(**FieldAggDBMeta.create_db_name_to_aggregate_lookup(self.statistics))[:10]
        df = read_frame(qs)
        df.rename(columns={self.grouping_field.db_name: self.grouping_field.name}, inplace=True)
        columns = [f.to_table_column() for f in [self.grouping_field] + self.statistics]
        return DataTable(
            source=ColumnDataSource(df),
            columns=columns, width=800)

    def create_timeseries_dataframe(self, levels=None):
        year_published_field = FieldDBMeta(db_name='year_published', name='year_published', title='Year Published')
        qs = self.queryset
        if levels:
            qs = qs.filter(**{'{}__in'.format(self.grouping_field.db_name): levels})
        df = read_frame(qs, fieldnames=['id', 'date_published_text', self.grouping_field.db_name])
        df[year_published_field.name] = [Publication(date_published_text=d).date_published for d in df['date_published_text']]
        df[year_published_field.name] = df[year_published_field.name].apply(lambda d: d.year if d is not None else None)
        df.drop('date_published_text', axis=1, inplace=True)
        return df.groupby([year_published_field.name, self.grouping_field.name])
