from django import forms
from django.forms import widgets
from django.contrib.auth import authenticate
from django.utils.translation import ugettext_lazy as _

from .models import Publication, JournalArticle

from haystack.forms import SearchForm


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=widgets.PasswordInput)

    def get_user(self):
        return self.user

    def clean(self):
        cleaned_data = super(LoginForm, self).clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')
        self.user = authenticate(username=username, password=password)
        if self.user is None:
            raise forms.ValidationError(
                _("Your combination of username and password was incorrect."), code='invalid')
        elif not self.user.is_active:
            raise forms.ValidationError(
                _("This user has been deactivated. Please contact us if this is in error."))
        return cleaned_data


class CustomSearchForm(SearchForm):

    STATUS_CHOICES = tuple([("", "Any"), ] + list(Publication.Status))

    publication_start_date = forms.DateField(required=False)
    publication_end_date = forms.DateField(required=False)
    contact_email = forms.BooleanField(required=False)
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)
    assigned_curator = forms.CharField(required=False)

    def no_query_found(self):
        return self.searchqueryset.all()

    def search(self, assigned_curator=None):
        # First, store the SearchQuerySet received from other processing.
        # NOTE: Keep on adding the publication subtypes to models below to show them in search
        sqs = super(CustomSearchForm, self).search().models(JournalArticle)

        if assigned_curator:
            return sqs.filter(assigned_curator=assigned_curator, status=Publication.Status.UNTAGGED).order_by()
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

        # Check to see if assigned_curator was selected.
        if self.cleaned_data['assigned_curator']:
            criteria.update(assigned_curator=self.cleaned_data['assigned_curator'])

        sqs = sqs.filter(**criteria)

        if self.cleaned_data['contact_email']:
            sqs = sqs.exclude(contact_email__exact='')

        # if not using query to search return the results sorted by date
        if not self.cleaned_data['q']:
            sqs = sqs.order_by('-pub_date')
        return sqs
