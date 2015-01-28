from django import forms
from django.forms import widgets, ValidationError
from django.contrib.auth import authenticate
from django.utils.translation import ugettext_lazy as _

from haystack.forms import SearchForm

from .models import Publication, JournalArticle


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
        exclude = ['date_added', 'date_modified']
        widgets = {
            'title': widgets.Textarea(attrs={'rows': 3}),
        }


class DateRangeSearchForm(SearchForm):
    start_date = forms.DateField(required=False)
    end_date = forms.DateField(required=False)

    def no_query_found(self):
        return self.searchqueryset.all()

    def search(self):
        # First, store the SearchQuerySet received from other processing.
        sqs = super(DateRangeSearchForm, self).search()

        if not self.is_valid():
            return self.no_query_found()

        # Check to see if a start_date was chosen.
        if self.cleaned_data['start_date']:
            sqs = sqs.filter(pub_date__gte=self.cleaned_data['start_date'])

        # Check to see if an end_date was chosen.
        if self.cleaned_data['end_date']:
            sqs = sqs.filter(pub_date__lte=self.cleaned_data['end_date'])

        return sqs
