import logging
from collections import namedtuple

import requests
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.forms import Form, ModelForm
from django.utils.translation import ugettext_lazy as _
from haystack.forms import SearchForm
from haystack.inputs import Raw

from citation.models import Author, Container, Platform, Publication, Sponsor, Tag, SuggestedPublication, Submitter, \
    AuthorCorrespondenceLog

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
    journal = forms.CharField(required=False)
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

        # Check to see if journal was selected.
        if self.cleaned_data['journal']:
            journal_object = self.cleaned_data['journal'].split()
            sqs = sqs.filter(container__in=journal_object)

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
            sqs = sqs.filter(contact_email=Raw('[* TO *]'))

        is_archived_string = self.cleaned_data.get('is_archived')
        if is_archived_string:
            sqs = sqs.filter(is_archived=(is_archived_string == 'True'))

        # if not using query to search, return the results sorted by date
        if not self.cleaned_data['q']:
            sqs = sqs.order_by('-date_published')
        return sqs


ContentTypeChoice = namedtuple('ContentTypeChoice', ['value', 'label', 'model'])

CONTENT_TYPE_CHOICES = [
    ContentTypeChoice(value=model._meta.verbose_name_plural, label=model._meta.verbose_name_plural.title(), model=model)
    for model in [Author, Platform, Sponsor, Tag]
]
CONTENT_TYPE_CHOICES.insert(1, ContentTypeChoice(Container._meta.verbose_name_plural, 'Journals and Other Media',
                                                 Container))

CONTENT_TYPE_SEARCH = {
    c.value: c.model for c in CONTENT_TYPE_CHOICES
}


class PublicSearchForm(Form):
    search = forms.CharField(label='Search')


class PublicExploreForm(Form):
    content_type = forms.ChoiceField(choices=[(c.value, c.label) for c in CONTENT_TYPE_CHOICES], label='Content Type')
    topic = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'Search'}))
    order_by = forms.ChoiceField(choices=(
        ('count', 'Publication Count Desc'), ('citations', 'Total Publication Citations Desc'),
        ('index', 'h-index Desc')))


class SuggestedPublicationForm(ModelForm):
    def __init__(self, *args, **kwargs):
        self.submitter = kwargs.pop('submitter', None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = SuggestedPublication
        fields = ['doi', 'code_archive_url', 'title', 'journal', 'volume', 'issue', 'pages']
        widgets = {
            'doi': forms.TextInput,
            'journal': forms.TextInput,
            'title': forms.TextInput,
        }
        help_texts = {
            'doi': 'A valid digital object identifier (should not include the URL https://doi.org)',
            'code_archive_url': 'A valid url to download all code, metadata and documentation necessary to run the model'
        }

    def clean_doi(self):
        response = requests.get('https://doi.org/{}'.format(self.cleaned_data['doi']))
        if response.status_code != 200:
            raise forms.ValidationError('Could not resolve DOI. DOI should not include protocol information (so 10.1109/access.2019.2896978 is valid and https://doi.org/10.1109/access.2019.2896978 is not)')
        return self.cleaned_data['doi']

    def clean(self):
        has_doi = bool(self.cleaned_data['doi'] if 'doi' in self.cleaned_data else False)
        has_title_and_journal = bool(self.cleaned_data['title'] and self.cleaned_data['journal'])
        if not (has_doi or has_title_and_journal):
            raise forms.ValidationError('Must have either a DOI or a title and journal')
        return super().clean()

    def save(self, commit=True):
        suggested_publication = SuggestedPublication(**self.cleaned_data, submitter=self.submitter)
        suggested_publication.save()
        return suggested_publication


class ContactAuthorsForm(Form):

    ARCHIVE_STATUS_CHOICES = [('', 'Any')] + AuthorCorrespondenceLog.CODE_ARCHIVE_STATUS

    email_filter = forms.EmailField(required=False,
                                    help_text=_("Author email address to additionally filter by for testing"))
    status = forms.ChoiceField(choices=ARCHIVE_STATUS_CHOICES, required=False)
    number_of_authors = forms.IntegerField(min_value=1, max_value=100, initial=10,
                                           help_text=_("Number of authors to contact (will be overridden by email_filter)"))
    custom_invitation_text = forms.CharField(widget=forms.Textarea, help_text=_("Custom invitation text"),
                                             required=False)
    ready_to_send = forms.BooleanField(required=False,
                                       help_text=_("Check this box to send the email out"))


class SubmitterForm(ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = Submitter
        fields = ['email']
        help_texts = {
            'email': 'Your email address. Not needed if you are logged in'
        }

    def clean_email(self):
        email = self.cleaned_data['email']
        if self.user is None and not email:
            raise forms.ValidationError('Must set an email address if are requesting anonymously')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Cannot set email address to that of an existing user')
        return email

    def save(self, commit=True):
        if self.user is not None:
            submitter = Submitter(user=self.user)
        else:
            submitter = Submitter(email=self.cleaned_data['email'])
        submitter.save()
        return submitter
