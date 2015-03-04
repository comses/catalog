from django.test import TestCase
from django.contrib.auth.models import User
from django.test.client import Client

class AuthTest(TestCase):
    def setUp(self):
         user = User.objects.create_user('temporary', 'temporary@gmail.com', 'temporary')
         self.client = Client()

    def test_login(self):
        res = self.client.login(username='temporary', password='temporary')
        self.assertTrue(res)
