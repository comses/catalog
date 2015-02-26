from django import forms
from django.forms import widgets, ValidationError
from django.contrib.auth import authenticate
from django.utils.translation import ugettext_lazy as _

from .models import Publication, JournalArticle, Tag, Sponsor, STATUS_CHOICES

from haystack.forms import SearchForm
from model_utils import Choices


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=widgets.PasswordInput)
    INVALID_AUTHENTICATION_MESSAGE = "Your combination of username and password was incorrect."

    def get_user(self):
        return self.user

    def clean(self):
        cleaned_data = super(LoginForm, self).clean()
        username = cleaned_data.get('username')
        if username:
            username = username.lower()
        password = cleaned_data.get('password')
        if username and password:
            self.user = authenticate(
                username=username, password=password)
            if self.user is None:
                raise forms.ValidationError(
                    _(LoginForm.INVALID_AUTHENTICATION_MESSAGE), code='invalid')
            elif not self.user.is_active:
                raise forms.ValidationError(
                    _("This user has been deactivated. Please contact us if this is in error."))
        return cleaned_data


class PublicationDetailForm(forms.ModelForm):
    class Meta:
        model = Publication
        exclude = ['date_added', 'date_modified']
        widgets = {
            'title': widgets.Textarea(attrs={'rows': 3}),
        }


class JournalArticleDetailForm(forms.ModelForm):
    class Meta:
        model = JournalArticle
        exclude = ['date_added', 'date_modified', 'added_by', 'date_published_text']
        widgets = {
            'title': widgets.Textarea(attrs={'rows': 3}),
        }


class CustomSearchForm(SearchForm):

    STATUS_CHOICES = tuple([("", "Any"), ] + list(STATUS_CHOICES))

    publication_start_date = forms.DateField(required=False)
    publication_end_date = forms.DateField(required=False)
    contact_email = forms.BooleanField(required=False)
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)

    def no_query_found(self):
        return self.searchqueryset.all()

    def search(self):
        # First, store the SearchQuerySet received from other processing.
        sqs = super(CustomSearchForm, self).search()

        if not self.is_valid():
            return self.no_query_found()

        criteria = dict()
        # Check to see if a start_date was chosen.
        if self.cleaned_data['publication_start_date']:
            criteria.update(pub_date__gte=self.cleaned_data['publication_start_date'])

        # Check to see if an end_date was chosen.
        if self.cleaned_data['publication_end_date']:
            criteria.update(pub_date__lte=self.cleaned_data['publication_end_date'])

        # Check to see if status was selected.
        if self.cleaned_data['status']:
            criteria.update(status=self.cleaned_data['status'])

        sqs = sqs.filter(**criteria)
        if self.cleaned_data['contact_email']:
            sqs = sqs.exclude(contact_email__exact='')

        # if not using query to search return the results sorted by date
        if not self.cleaned_data['q']:
            sqs = sqs.order_by('-pub_date')
        return sqs
