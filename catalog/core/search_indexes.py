from haystack import indexes
from citation.models import Publication, Platform, Sponsor, Tag, Container, ModelDocumentation

##########################################
#  Publication query seach/filter index  #
##########################################

class PublicationIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    title = indexes.CharField(model_attr='title')
    date_published = indexes.DateField(model_attr='date_published', null=True)
    last_modified = indexes.DateTimeField(model_attr='date_modified')
    contact_email = indexes.BooleanField(model_attr='contact_email')
    status = indexes.CharField(model_attr='status', faceted=True)
    container = indexes.EdgeNgramField(model_attr='container__name',null=True)
    tags = indexes.EdgeNgramField(model_attr='tags__name', null=True)
    authors = indexes.EdgeNgramField(model_attr='creators__name', null=True)
    assigned_curator = indexes.CharField(model_attr='assigned_curator', null=True)
    flagged = indexes.BooleanField(model_attr='flagged')
    is_primary = indexes.BooleanField(model_attr='is_primary')
    is_archived = indexes.BooleanField(model_attr='is_archived')
    contributor_data = indexes.MultiValueField(model_attr='contributor_data', null=True)

    def prepare_last_modified(self, obj):
        last_modified = self.prepared_data.get('last_modified')
        if last_modified:
            return last_modified.strftime('%Y-%m-%dT%H:%M:%SZ')
        return ''

    def prepare_contributor_data(self, obj):
        contributor_data = self.prepared_data.get('contributor_data')
        if contributor_data:
            return contributor_data[0]['creator'] + ' (' + str(contributor_data[0]['contribution']) + ')%'
        return ''

    def get_model(self):
        return Publication

    def index_queryset(self, using=None):
        return Publication.objects.filter(is_primary=True)


##########################################
#       AutoComplete Index Fields        #
##########################################

class NameAutocompleteIndex(indexes.SearchIndex):
    text = indexes.CharField(document=True)
    name = indexes.NgramField(model_attr='name')

    class Meta:
        abstract = True


class PlatformIndex(NameAutocompleteIndex, indexes.Indexable):
    def get_model(self):
        return Platform


class SponsorIndex(NameAutocompleteIndex, indexes.Indexable):
    def get_model(self):
        return Sponsor


class TagIndex(NameAutocompleteIndex, indexes.Indexable):
    def get_model(self):
        return Tag


class ModelDocumentationIndex(NameAutocompleteIndex, indexes.Indexable):
    def get_model(self):
        return ModelDocumentation

##########################################
#           Bulk Index Updates           #
##########################################

def bulk_index_update():
    PublicationIndex().update()
    PlatformIndex().update()
    SponsorIndex().update()
    TagIndex().update()
    ModelDocumentationIndex().update()
