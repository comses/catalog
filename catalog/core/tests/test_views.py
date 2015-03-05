from django.contrib.auth.models import User
from django.core import management
from catalog.core.models import Publication

from .common import BaseTest


class AuthTest(BaseTest):

    def test_login(self):
        response = self.get(self.login_url)
        self.assertTrue(200, response.status_code)

    def test_login_with_bad_credentials(self):
        response = self.post(self.login_url, {'username':'wrong_username', 'password':'temporary'})
        self.assertTrue(200, response.status_code)

    def test_login_with_good_credentials(self):
        response = self.post(self.login_url, {'username':'temporary', 'password':'temporary'})
        self.assertTrue(200, response.status_code)
        self.assertTrue(self.reverse('dashboard') in response['Location'])

    def test_login_with_inactive_user(self):
        User.objects.filter(username='temporary').update(is_active=False)
        response = self.post(self.login_url, {'username':'temporary', 'password':'temporary'})
        self.assertTrue(200, response.status_code)

    def test_logout(self):
        response = self.get(self.reverse('logout'))
        self.assertTrue(302, response.status_code)


class IndexViewTest(BaseTest):
    def test_index_view(self):
        self.without_login_and_with_login_test(self.reverse('login'), before_status=200)


class DashboardViewTest(BaseTest):
    def test_dashboard_view(self):
        self.without_login_and_with_login_test(self.reverse('dashboard'))


class PublicationsViewTest(BaseTest):
    def test_publications_view(self):
        url = self.reverse('publications')
        self.without_login_and_with_login_test(url)

    def test_publication_view_with_query_parameter(self):
        self.login()
        url = self.reverse('publications')
        response = self.get(url + "?page=-1")
        self.assertEqual(200, response.status_code)


class PublicationDetailView(BaseTest):
    def test_publication_detail_view(self):
        management.call_command('zotero_import', test=True)
        url = self.reverse('publication_detail', kwargs={'pk': Publication.objects.all()[0].pk})
        self.without_login_and_with_login_test(url)

        self.logout()
        url = self.reverse('publication_detail', kwargs={'pk': 999999})
        self.without_login_and_with_login_test(url, after_status=404)

        # test json data api
        # FIXME: consider moving it to test_api.py
        self.logout()
        url = self.reverse('publication_detail', query_parameters={'format':'json'}, kwargs={'pk': Publication.objects.all()[0].pk})
        self.without_login_and_with_login_test(url)

        self.logout()
        url = self.reverse('publication_detail', query_parameters={'format':'json'}, kwargs={'pk': 999999})
        self.without_login_and_with_login_test(url, after_status=404)


class SearchViewTest(BaseTest):
    def test_search_with_no_query_parameters(self):
        self.without_login_and_with_login_test(self.reverse('haystack_search'))

    def test_search_with_all_query_parameters(self):
        query_parameters = {
                'q': 'model',
                'publication_start_date':'1/1/2014',
                'publication_end_date':'1/1/2015',
                'contact_email':'on',
                'status':'INCOMPLETE'
            }
        url = self.reverse('haystack_search', query_parameters=query_parameters)
        self.without_login_and_with_login_test(url)

    def test_search_with_few_query_parameters(self):
        query_parameters = {
                'q': '',
                'publication_start_date':'1/1/2014',
                'publication_end_date':'1/1/2015',
                'contact_email':'on',
                'status':'INCOMPLETE'
            }
        url = self.reverse('haystack_search', query_parameters=query_parameters)
        self.without_login_and_with_login_test(url)


class ContactViewTest(BaseTest):
    def test_contact_view(self):
        self.without_login_and_with_login_test(self.reverse('contact_us'), before_status=200)


class EmailPreviewTest(BaseTest):
    def test_email_preview_without_query_parameters(self):
        self.login()
        response = self.get(self.reverse('invite_email_preview'))
        self.assertEqual(400, response.status_code)

    def test_email_preview_with_query_parameters(self):
        self.login()
        url = self.reverse('invite_email_preview', query_parameters={'invitation_subject':'test','invitation_text':'test'})
        response = self.get(url)
        self.assertEqual(200, response.status_code)
