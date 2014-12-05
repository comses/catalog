from django import forms
from django.forms import widgets, ValidationError
from django.contrib.auth import authenticate
from django.utils.translation import ugettext_lazy as _

from .models import Publication

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
