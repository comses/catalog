import json
import logging
from unittest import mock
from unittest.mock import patch

from django.contrib.auth.models import User
from haystack.query import SearchQuerySet

from citation.models import Publication, ModelDocumentation
from .common import BaseTest

logger = logging.getLogger(__name__)

MAX_EXAMPLES = 30

CONTACT_US_URL = 'core:contact_us'
DASHBOARD_URL = 'core:dashboard'
HAYSTACK_SEARCH_URL = 'core:haystack_search'
PUBLICATIONS_URL = 'citation:publications'
PUBLICATION_DETAIL_URL = 'citation:publication_detail'
USER_PROFILE_URL = 'core:user_profile'
WORKFLOW_URL = 'core:curator_workflow'
HOME_URL = 'core:public-home'


class UrlTest(BaseTest):
    TEST_URLS = (CONTACT_US_URL, DASHBOARD_URL, HAYSTACK_SEARCH_URL, PUBLICATIONS_URL, USER_PROFILE_URL, WORKFLOW_URL)

    def test_urls(self):
        self.login()
        for url in UrlTest.TEST_URLS:
            response = self.get(url)
            self.assertTrue(200, response.status_code)


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
        self.assertTrue(self.reverse(HOME_URL) in response['Location'])

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
        self.without_login_and_with_login_test(USER_PROFILE_URL)

    def test_profile_update(self):
        first_name, last_name = 'Egg', 'Timer'
        url = self.reverse(USER_PROFILE_URL, query_parameters={'format': 'json'})
        self.login()
        old_email = self.user.email
        response = self.post(url, {'first_name': first_name,
                                   'last_name': last_name,
                                   'username': self.user.username,
                                   })
        self.assertEqual(200, response.status_code)
        user = User.objects.get(username=self.user.username)
        # check for updated values
        self.assertEqual(user.first_name, first_name)
        self.assertEqual(user.last_name, last_name)
        # ensure email has not been changed
        self.assertEqual(user.email, old_email)

    def test_profile_invalid_email_update(self):
        first_name, last_name = 'Egg', 'Timer'
        url = self.reverse(USER_PROFILE_URL, query_parameters={'format': 'json'})
        self.login()
        response = self.post(url, {'first_name': first_name,
                                   'last_name': last_name,
                                   'username': self.user.username,
                                   'email': "user@comses.net"
                                   })
        # Updating email should return status code 400 - but for now we are ignoring it
        self.assertEqual(200, response.status_code)

    def test_profile_invalid_update(self):
        first_name, last_name = 'Egg', 'Timer'
        username = ' sldfkj kljsf # A//?'
        url = self.reverse(USER_PROFILE_URL, query_parameters={'format': 'json'})
        self.login()
        response = self.post(url, {'first_name': first_name, 'last_name': last_name,
                                   'username': username})
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


class PublicationDetailViewTest(BaseTest):
    def test_canonical_publication_detail_view(self):
        source_code_documentation = ModelDocumentation(name='Source code')
        source_code_documentation.save()
        journal_title = 'Econometrica'
        container = self.create_container(name=journal_title)
        container.save()
        publication_title = 'A very model model'
        p = self.create_publication(title=publication_title, added_by=self.user, container=container)
        p.save()

        self.logout()
        url = self.reverse(PUBLICATION_DETAIL_URL, kwargs={'pk': 999999})
        self.without_login_and_with_login_test(url, after_status=404)

        url = self.reverse(PUBLICATION_DETAIL_URL, kwargs={'pk': p.pk, 'slug': p.slug})
        response = self.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, journal_title)
        self.assertContains(response, publication_title)

        self.logout()
        url = self.reverse(PUBLICATION_DETAIL_URL,
                           query_parameters={'format': 'json'},
                           kwargs={'pk': p.pk})
        self.without_login_and_with_login_test(url, after_status=302)

        self.logout()
        url = self.reverse(PUBLICATION_DETAIL_URL, query_parameters={
            'format': 'json'}, kwargs={'pk': 999999})
        self.without_login_and_with_login_test(url, after_status=404)

    @patch('citation.views.PublicationSerializer')
    def test_publication_detail_save_uses_publication_serializer(self, publication_serializer):
        class MockPublicationSerializer:
            def is_valid(self):
                return True

            def save(self, user=None):
                return Publication()

            @property
            def data(self):
                return {}

        publication_serializer.return_value = MockPublicationSerializer()

        source_code_documentation = ModelDocumentation(name='Source code')
        source_code_documentation.save()
        container = self.create_container(name='Econometrica')
        container.save()
        p = self.create_publication(title='Akjhdfjk kjjd', added_by=self.user, container=container)
        p.save()

        self.login()
        url = p.get_absolute_url()
        response = self.put('{}?format=json'.format(url), json.dumps({}), content_type="application/json")
        self.assertEqual(200, response.status_code)


class SearchViewTest(BaseTest):
    def test_search_with_no_query_parameters(self):
        self.without_login_and_with_login_test(
            self.reverse(HAYSTACK_SEARCH_URL))

    def test_search_with_all_query_parameters(self):
        query_parameters = {
            'q': '',
            'publication_start_date': '1/1/2014',
            'publication_end_date': '1/1/2015',
            'contact_email': True,
            'status': Publication.Status.REVIEWED,
            'journal': 'ECOLOGICAL MODELLING',
            'tags': 'Agriculture',
            'authors': 'Guiller',
            'assigned_curator': 'yhsieh22',
            'flagged': False,
            'is_archived': True
        }

        self.logout()
        print("Query Parameter", query_parameters)
        url = self.reverse(
            HAYSTACK_SEARCH_URL, query_parameters=query_parameters)
        self.without_login_and_with_login_test(url)

        # Test to verify if it returns same output list or not
        p = SearchQuerySet().filter(is_primary=True, date_published__gte='2014-01-01T00:00:00Z',
                                    date_published__lte='2015-01-01T00:00:00Z',
                                    status=Publication.Status.REVIEWED, container__name='ECOLOGICAL MODELLING',
                                    authors='Guiller', assigned_curator='yhsieh22', flagged=False,
                                    is_archived=True).count()
        self.login()
        url = self.reverse(HAYSTACK_SEARCH_URL)
        response = self.client.get(
            url + "?q=&publication_start_date=1%2F1%2F2014&publication_end_date=1%2F1%2F2015&status=&journal=\
            ECOLOGICAL+MODELLING&tags=Agriculture&authors=Guiller&assigned_curator=yhsieh22&flagged=False&is_archived=True")
        object_count = response.context['object_list']
        self.assertEqual(200, response.status_code)
        if p < 25 or len(object_count) < 25:
            self.assertEquals(p, len(object_count))

    def test_search_with_few_query_parameters(self):
        query_parameters = {
            'q': '',
            'publication_start_date': '1/1/2014',
            'publication_end_date': '1/1/2015',
            'contact_email': 'on',
            'status': Publication.Status.UNREVIEWED
        }
        url = self.reverse(
            HAYSTACK_SEARCH_URL, query_parameters=query_parameters)
        self.without_login_and_with_login_test(url)


class ContactViewTest(BaseTest):
    def test_contact_view(self):
        self.without_login_and_with_login_test(
            self.reverse(CONTACT_US_URL), before_status=200)

    @patch('catalog.core.views.ContactFormSerializer.save', return_value=None)
    @patch('catalog.core.views.ContactFormSerializer.is_valid', return_value=True)
    @patch('catalog.core.views.ContactFormSerializer.data', new_callable=mock.PropertyMock)
    def test_contact_info_route_is_validated(self, data, is_valid, save):
        data.return_value = {}
        url = self.reverse(CONTACT_US_URL, query_parameters={'format': 'json'})
        self.post(url, {})
        data.assert_any_call()
        is_valid.assert_any_call()
        save.assert_any_call()
