from haystack import indexes
from .models import Publication, Platform, Sponsor, Tag, Journal, ModelDocumentation


class PublicationIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    title = indexes.CharField(model_attr='title')
    pub_date = indexes.DateField(model_attr='date_published', null=True)
    contact_email = indexes.BooleanField(model_attr='contact_email')
    status = indexes.CharField(model_attr='status')

    def get_model(self):
        return Publication

    def index_queryset(self, using=None):
        """Used when the entire index for model is updated."""
        return self.get_model().objects.all()


class PlatformIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    def get_model(self):
        return Platform

    def index_queryset(self, using=None):
        """Used when the entire index for model is updated."""
        return self.get_model().objects.all()


class SponsorIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    def get_model(self):
        return Sponsor

    def index_queryset(self, using=None):
        """Used when the entire index for model is updated."""
        return self.get_model().objects.all()


class TagIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    value = indexes.NgramField(model_attr='value')

    def get_model(self):
        return Tag

    def index_queryset(self, using=None):
        """Used when the entire index for model is updated."""
        return self.get_model().objects.all()

class JournalIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    def get_model(self):
        return Journal

    def index_queryset(self, using=None):
        """Used when the entire index for model is updated."""
        return self.get_model().objects.all()


class ModelDocIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    value = indexes.NgramField(model_attr='value')

    def get_model(self):
        return ModelDocumentation

    def index_queryset(self, using=None):
        """Used when the entire index for model is updated."""
        return self.get_model().objects.all()

