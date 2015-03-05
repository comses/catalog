from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import Client
from django.utils.http import urlencode


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

    def without_login_and_with_login_test(self, url, before_status=302, after_status=200):
        response = self.get(url)
        self.assertEqual(before_status, response.status_code)

        if before_status is not 200:
            self.assertTrue(self.login_url in response['Location'])

        self.login()

        response = self.get(url)
        self.assertEqual(after_status, response.status_code)

    def get(self, url, *args, **kwargs):
        if ':' in url:
            url = self.reverse(url)
        return self.client.get(url, *args, **kwargs)

    def post(self, url, *args, **kwargs):
        if ':' in url:
            url = self.reverse(url)
        response = self.client.post(url, *args, **kwargs)
        return response

