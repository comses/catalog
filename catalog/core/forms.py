from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import ugettext_lazy as _

from citation.models import Publication
from haystack.forms import SearchForm

import logging

logger = logging.getLogger(__name__)


class CatalogAuthenticationForm(AuthenticationForm):
    username = forms.CharField(max_length=254, widget=forms.TextInput(attrs={'autofocus': True}))


class CatalogSearchForm(SearchForm):
    STATUS_CHOICES = [("", "Any")] + Publication.Status
    ANY_CHOICES = [("", "Any"), ("True", "True"), ("False", "False")]

    publication_start_date = forms.DateField(required=False)
    publication_end_date = forms.DateField(required=False)
    contact_email = forms.BooleanField(required=False)
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)
    tags = forms.CharField(required=False, widget=forms.Select(attrs={'multiple': "multiple", 'name': "tags",
                                                                      'data-bind': "selectize: tags, selectedOptions: selectedTags, optionsCaption: 'Keywords', optionsValue: 'name', options: { create: false, load: getTagList, hideSelected: true }, value: SelectedTags"}))
    authors = forms.CharField(required=False)
    assigned_curator = forms.CharField(required=False)
    flagged = forms.ChoiceField(choices=ANY_CHOICES, required=False)
    is_archived = forms.ChoiceField(choices=ANY_CHOICES, required=False, label=_("Has code URL"))

    def no_query_found(self):
        return self.searchqueryset.filter(is_primary=True).models(Publication).all()

    def __init__(self, *args, **kwargs):
        self.tags = kwargs.pop('tag_list', None)
        super(CatalogSearchForm, self).__init__(*args, **kwargs)

    def clean(self):
        super(CatalogSearchForm, self).clean()
        cleaned_data = self.cleaned_data
        cleaned_data['tags'] = self.tags

    def search(self):
        # First, store the SearchQuerySet received from other processing.
        # NOTE: Keep on adding the publication subtypes to models below to show them in search
        if not self.is_valid():
            return self.no_query_found()

        sqs = super(CatalogSearchForm, self).search()
        logger.debug("searching on %s", self.cleaned_data)

        criteria = {}
        # Check to see if a start_date was chosen.
        if self.cleaned_data['publication_start_date']:
            criteria.update(date_published__gte=self.cleaned_data['publication_start_date'])

        # Check to see if an end_date was chosen.
        if self.cleaned_data['publication_end_date']:
            criteria.update(date_published__lte=self.cleaned_data['publication_end_date'])

        # Check to see if status was selected.
        if self.cleaned_data['status']:
            criteria.update(status=self.cleaned_data['status'])

        # Check to see if tags was selected.
        if self.cleaned_data['tags']:
            tags_object = self.cleaned_data['tags']
            sqs = sqs.filter(tags__in=tags_object)

        # Check to see if authors was selected.
        if self.cleaned_data['authors']:
            authors_object = self.cleaned_data['authors'].split()
            sqs = sqs.filter(authors__in=authors_object)

        # Check to see if assigned_curator was selected.
        if self.cleaned_data['assigned_curator']:
            criteria.update(assigned_curator=self.cleaned_data['assigned_curator'])

        # Check to see if flagged was set
        flagged_string = self.cleaned_data.get('flagged')
        if flagged_string:
            criteria.update(flagged=(flagged_string == "True"))

        sqs = sqs.filter(**criteria)

        if self.cleaned_data['contact_email']:
            sqs = sqs.exclude(contact_email='')

        is_archived_string = self.cleaned_data.get('is_archived')
        if is_archived_string:
            sqs = sqs.filter(is_archived=(is_archived_string == 'True'))

        # if not using query to search, return the results sorted by date
        if not self.cleaned_data['q']:
            sqs = sqs.order_by('-date_published')
        return sqs
