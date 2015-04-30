from haystack import indexes
from .models import JournalArticle, Platform, Sponsor, Tag, Journal, ModelDocumentation


##########################################
#  Publication query seach/filter index  #
##########################################

class PublicationIndex(indexes.SearchIndex):
    text = indexes.CharField(document=True, use_template=True)
    title = indexes.CharField(model_attr='title')
    pub_date = indexes.DateField(model_attr='date_published', null=True)
    contact_email = indexes.BooleanField(model_attr='contact_email')
    status = indexes.CharField(model_attr='status')
    assigned_curator = indexes.CharField(model_attr='assigned_curator', null=True)

    class Meta:
        abstract = True


class JournalArticleIndex(PublicationIndex, indexes.Indexable):
    def get_model(self):
        return JournalArticle


##########################################
#       AutoComplete Index Fields        #
##########################################

class ValueAutoCompleteIndex(indexes.SearchIndex):
    text = indexes.CharField(document=True)
    value = indexes.NgramField(model_attr='value')

    class Meta:
        abstract = True


class NameAutoCompleteIndex(indexes.SearchIndex):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    class Meta:
        abstract = True


class PlatformIndex(NameAutoCompleteIndex, indexes.Indexable):
    def get_model(self):
        return Platform


class SponsorIndex(NameAutoCompleteIndex, indexes.Indexable):
    def get_model(self):
        return Sponsor


class TagIndex(ValueAutoCompleteIndex, indexes.Indexable):
    def get_model(self):
        return Tag


class JournalIndex(NameAutoCompleteIndex, indexes.Indexable):
    def get_model(self):
        return Journal


class ModelDocIndex(ValueAutoCompleteIndex, indexes.Indexable):
    def get_model(self):
        return ModelDocumentation
