from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import Client


class BaseTest(TestCase):
    def setUp(self):
        user = User.objects.create_user('temporary', 'temporary@gmail.com', 'temporary')

    @property
    def login_url(self):
        return reverse('login')

    def login(self):
        return self.client.login(username='temporary', password='temporary')

    def logout(self):
        return self.client.logout()

    def reverse(self, viewname, query_parameters=None, **kwargs):
        reversed_url = reverse(viewname, **kwargs)
        if query_parameters is not None:
            return '%s?%s' % (reversed_url, urlencode(query_parameters))
        return reversed_url

    def get(self, url, *args, **kwargs):
        if ':' in url:
            url = self.reverse(url)
        return self.client.get(url, *args, **kwargs)

    def post(self, url, *args, **kwargs):
        if ':' in url:
            url = self.reverse(url)
        response = self.client.post(url, *args, **kwargs)
        return response

