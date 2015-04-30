from haystack import indexes
from .models import JournalArticle, Platform, Sponsor, Tag, Journal, ModelDocumentation


class PublicationIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    title = indexes.CharField(model_attr='title')
    pub_date = indexes.DateField(model_attr='date_published', null=True)
    contact_email = indexes.BooleanField(model_attr='contact_email')
    status = indexes.CharField(model_attr='status')
    assigned_curator = indexes.CharField(model_attr='assigned_curator', null=True)

    def get_model(self):
        return JournalArticle


class PlatformIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    def get_model(self):
        return Platform


class SponsorIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    def get_model(self):
        return Sponsor


class TagIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    value = indexes.NgramField(model_attr='value')

    def get_model(self):
        return Tag


class JournalIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    def get_model(self):
        return Journal


class ModelDocIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    value = indexes.NgramField(model_attr='value')

    def get_model(self):
        return ModelDocumentation
