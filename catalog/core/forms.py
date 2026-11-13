import logging
from collections import namedtuple

import requests
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.forms import Form, ModelForm
from django.utils.translation import gettext_lazy as _

from citation.models import Author, Container, Platform, Publication, Sponsor, Tag, SuggestedPublication, Submitter, \
    AuthorCorrespondenceLog

from .search_indexes import build_curator_publication_search

logger = logging.getLogger(__name__)


class CatalogAuthenticationForm(AuthenticationForm):
    username = forms.CharField(max_length=254, widget=forms.TextInput(attrs={'autofocus': True}))


class CatalogSearchForm(Form):
    STATUS_CHOICES = [("", "Any")] + Publication.Status
    ANY_CHOICES = [("", "Any"), ("True", "True"), ("False", "False")]

    q = forms.CharField(required=False, label='Search')
    publication_start_date = forms.DateField(required=False)
    publication_end_date = forms.DateField(required=False)
    contact_email = forms.BooleanField(required=False)
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)
    journal = forms.CharField(required=False)
    tags = forms.CharField(required=False, widget=forms.Select(attrs={'multiple': "multiple", 'name': "tags",
                                                                      'data-bind': "selectize: tags, selectedOptions: selectedTags, optionsCaption: 'Keywords', optionsValue: 'name', options: { create: false, load: getTagList, hideSelected: true }"}))
    authors = forms.CharField(required=False)
    assigned_curator = forms.CharField(required=False)
    flagged = forms.ChoiceField(choices=ANY_CHOICES, required=False)
    is_archived = forms.ChoiceField(choices=ANY_CHOICES, required=False, label=_("Has code URL"))

    def __init__(self, *args, **kwargs):
        self.tags = kwargs.pop('tag_list', None)
        super(CatalogSearchForm, self).__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if self.tags is not None:
            cleaned_data['tags'] = self.tags
        return cleaned_data

    def search(self, search=None):
        if not self.is_valid():
            return build_curator_publication_search({}, search=search)
        logger.debug("searching on %s", self.cleaned_data)
        return build_curator_publication_search(self.cleaned_data, search=search)


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
