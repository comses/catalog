from django.contrib.auth.models import User
from django.core import management
from citation.models import Publication

from .common import BaseTest

import json
import time

CONTACT_US_URL = 'core:contact_us'
DASHBOARD_URL = 'core:dashboard'
HAYSTACK_SEARCH_URL = 'core:haystack_search'
INVITE_EMAIL_PREVIEW_URL = 'core:invite_email_preview'
PUBLICATIONS_URL = 'citation:publications'
PUBLICATION_DETAIL_URL = 'citation:publication_detail'
USER_PROFILE_URL = 'core:user_profile'


class AuthTest(BaseTest):
    def test_login(self):
        response = self.get(self.login_url)
        self.assertTrue(200, response.status_code)

    def test_login_with_bad_credentials(self):
        response = self.post(
            self.login_url, {'username': 'wrong_username', 'password': 'temporary'})
        self.assertTrue(200, response.status_code)
        self.assertTrue(b'Please enter a correct username and password.' in response.content)

    def test_login_with_good_credentials(self):
        response = self.post(self.login_url, {'username': self.default_username, 'password': self.default_password})
        self.assertTrue(200, response.status_code)
        self.assertTrue(self.reverse(DASHBOARD_URL) in response['Location'])

    def test_login_with_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        response = self.post(self.login_url, {'username': self.default_username, 'password': self.default_password})
        self.assertTrue(200, response.status_code)

    def test_logout(self):
        response = self.get(self.logout_url)
        self.assertTrue(302, response.status_code)


class ProfileViewTest(BaseTest):
    def test_profile_view(self):
        self.without_login_and_with_login_test('core:user_profile')

    def test_profile_update(self):
        url = self.reverse(USER_PROFILE_URL, query_parameters={'format': 'json'})
        self.login()
        old_email = self.user.email
        response = self.post(url, {'first_name': 'Updated Firstname',
                                   'last_name': 'Updated Lastname',
                                   'username': self.user.username,
                                   })
        self.assertTrue(200, response.status_code)
        user = User.objects.get(username=self.user.username)
        # check for updated values
        self.assertEqual(user.first_name, 'Updated Firstname')
        self.assertEqual(user.last_name, 'Updated Lastname')
        # ensure email has not been changed
        self.assertEqual(user.email, old_email)

    def test_profile_invalid_update(self):
        url = self.reverse(USER_PROFILE_URL, query_parameters={'format': 'json'})
        self.login()
        response = self.post(url, {'first_name': 'Test', 'last_name': 'Test'})
        self.assertTrue(400, response.status_code)


class IndexViewTest(BaseTest):
    def test_index_view(self):
        self.without_login_and_with_login_test(self.index_url, before_status=200)


class DashboardViewTest(BaseTest):
    def test_dashboard_view(self):
        self.without_login_and_with_login_test(DASHBOARD_URL)


class PublicationsViewTest(BaseTest):
    def test_publications_view(self):
        self.without_login_and_with_login_test(PUBLICATIONS_URL)

    def test_publication_view_with_query_parameter(self):
        self.login()
        url = self.reverse(PUBLICATIONS_URL)
        response = self.get(url + "?page=-1")
        self.assertEqual(404, response.status_code)


class PublicationDetailView(BaseTest):
    def test_canonical_publication_detail_view(self):
        management.call_command('zotero_import', test=True)
        p = Publication.objects.first()

        url = self.reverse(PUBLICATION_DETAIL_URL, kwargs={'pk': p.pk})
        self.without_login_and_with_login_test(url, after_status=302)

        self.logout()
        url = self.reverse(PUBLICATION_DETAIL_URL, kwargs={'pk': 999999})
        self.without_login_and_with_login_test(url, after_status=404)

        # test that invalid slug values redirect to canonical slug values
        for invalid_slug in ('_', 'farfle', 'slartibartfast', 'canon', '19'):
            url = self.reverse(PUBLICATION_DETAIL_URL, kwargs={'pk': p.pk, 'slug': invalid_slug})
            response = self.get(url)
            self.assertEqual(response.url, p.get_absolute_url())

        self.logout()
        url = self.reverse(PUBLICATION_DETAIL_URL,
                           query_parameters={'format': 'json'},
                           kwargs={'pk': p.pk})
        self.without_login_and_with_login_test(url, after_status=302)

        self.logout()
        url = self.reverse(PUBLICATION_DETAIL_URL, query_parameters={
            'format': 'json'}, kwargs={'pk': 999999})
        self.without_login_and_with_login_test(url, after_status=404)

    #Test that publication detail is saved successfully or not
    def test_publication_detail_save_with_all_valid_fields(self):
        management.call_command('zotero_import', test=True)
        p = Publication.objects.first()
        url = self.reverse('citation:publication_detail', query_parameters={'format': 'json'},
                           kwargs={'pk': p.pk, 'slug': 'garbage text'})
        response = self.put(url, {})
        self.assertTrue(200, response.status_code)

class SearchViewTest(BaseTest):
    def test_search_with_no_query_parameters(self):
        self.without_login_and_with_login_test(
            self.reverse(HAYSTACK_SEARCH_URL))

    def test_search_with_all_query_parameters(self):
        query_parameters = {
            'q': 'model',
            'publication_start_date': '1/1/2014',
            'publication_end_date': '1/1/2015',
            'contact_email': 'on',
            'status': 'INCOMPLETE'
        }
        url = self.reverse(
            HAYSTACK_SEARCH_URL, query_parameters=query_parameters)
        self.without_login_and_with_login_test(url)

    def test_search_with_few_query_parameters(self):
        query_parameters = {
            'q': '',
            'publication_start_date': '1/1/2014',
            'publication_end_date': '1/1/2015',
            'contact_email': 'on',
            'status': 'INCOMPLETE'
        }
        url = self.reverse(
            HAYSTACK_SEARCH_URL, query_parameters=query_parameters)
        self.without_login_and_with_login_test(url)


class ContactViewTest(BaseTest):
    def test_contact_view(self):
        self.without_login_and_with_login_test(
            self.reverse(CONTACT_US_URL), before_status=200)

    def test_contact_info_submit_without_timestamp_and_security_hash(self):
        response = self.post(self.reverse(CONTACT_US_URL, query_parameters={'format': 'json'}),
                             {'name': 'John Watson', 'email': 'john@watson.com',
                              'message': 'Sherlock want to use this application.'})
        self.assertTrue(400, response.status_code)

    def test_contact_info_submit_with_invalid_timestamp(self):
        url = self.reverse(
            CONTACT_US_URL, query_parameters={'format': 'json'})
        response = self.get(url)
        json_data = json.loads(response.data['json'])
        security_hash = json_data['security_hash']
        timestamp = float(json_data['timestamp']) + 1

        response = self.post(url, {'name': 'John Watson',
                                   'email': 'john@watson.com',
                                   'message': 'Sherlock want to use this application.',
                                   'timestamp': timestamp,
                                   'security_hash': security_hash,
                                   'contact_number': ''})
        self.assertTrue(400, response.status_code)

    def test_contact_info_submit_with_valid_timestamp_and_invalid_security_hash(self):
        url = self.reverse(
            CONTACT_US_URL, query_parameters={'format': 'json'})
        response = self.get(url)
        json_data = json.loads(response.data['json'])
        security_hash = json_data['security_hash'] + 'fake'
        timestamp = json_data['timestamp']
        time.sleep(5)

        response = self.post(url, {'name': 'John Watson', 'email': 'john@watson.com',
                                   'message': 'Sherlock want to use this application.',
                                   'timestamp': timestamp,
                                   'security_hash': security_hash,
                                   'contact_number': ''})
        self.assertTrue(400, response.status_code)

    def test_contact_info_submit_with_honeypot_field(self):
        url = self.reverse(
            CONTACT_US_URL, query_parameters={'format': 'json'})
        response = self.get(url)
        json_data = json.loads(response.data['json'])
        security_hash = json_data['security_hash']
        timestamp = json_data['timestamp']

        time.sleep(5)
        response = self.post(url, {'name': 'John Watson', 'email': 'john@watson.com',
                                   'message': 'Sherlock want to use this application.',
                                   'timestamp': timestamp,
                                   'security_hash': security_hash,
                                   'contact_number': 'bot alert'})
        self.assertTrue(400, response.status_code)

    def test_contact_info_submit_with_all_valid_fields(self):
        url = self.reverse(CONTACT_US_URL, query_parameters={'format': 'json'})
        response = self.get(url)
        json_data = json.loads(response.data['json'])
        security_hash = json_data['security_hash']
        timestamp = json_data['timestamp']
        time.sleep(5)

        response = self.post(url, {'name': 'John Watson', 'email': 'john@watson.com',
                                   'message': 'Sherlock want to use this application.',
                                   'timestamp': timestamp, 'security_hash': security_hash,
                                   'contact_number': ''})
        self.assertTrue(200, response.status_code)


class EmailPreviewTest(BaseTest):
    def test_email_preview_without_query_parameters(self):
        self.login()
        response = self.get(INVITE_EMAIL_PREVIEW_URL)
        self.assertEqual(400, response.status_code)

    def test_email_preview_with_query_parameters(self):
        self.login()
        url = self.reverse(INVITE_EMAIL_PREVIEW_URL,
                           query_parameters={'invitation_subject': 'test', 'invitation_text': 'test'})
        response = self.get(url)
        self.assertEqual(200, response.status_code)


class CuratorWorkflowTest(BaseTest):
    def test_edits(self):
        pass
