from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.utils.http import urlencode

import logging

logger = logging.getLogger(__name__)


class BaseTest(TestCase):
    login_url = reverse('login')
    logout_url = reverse('logout')
    index_url = reverse('core:index')
    default_username = 'testcase'
    default_email = 'testcase@mailinator.com'
    default_password = 'testing'

    def setUp(self):
        self.user = self.create_user()

    def create_user(self, username=None, email=None, password=None, **kwargs):
        if username is None:
            username = self.default_username
        if email is None:
            email = self.default_email
        if password is None:
            password = self.default_password
        return User.objects.create_user(username=username, email=email, password=password, **kwargs)

    def login(self, username=None, password=None):
        if username is None:
            username = self.default_username
        if password is None:
            password = self.default_password
        return self.client.login(username=username, password=password)

    def logout(self):
        return self.client.logout()

    def reverse(self, viewname, query_parameters=None, **kwargs):
        reversed_url = reverse(viewname, **kwargs)
        if query_parameters is not None:
            return '%s?%s' % (reversed_url, urlencode(query_parameters))
        return reversed_url

    def without_login_and_with_login_test(self, url, before_status=302, after_status=200):
        if ':' in url:
            url = self.reverse(url)
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
