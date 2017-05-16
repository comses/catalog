from django.contrib.auth.models import User
from haystack.query import SearchQuerySet

from citation.models import Publication, Container, Platform, Sponsor, ModelDocumentation, Note, Tag, Author

from hypothesis.extra.django.models import models
from hypothesis import given, strategies as st, settings
from .common import BaseTest

import json

MAX_EXAMPLES = 30

CONTACT_US_URL = 'core:contact_us'
DASHBOARD_URL = 'core:dashboard'
HAYSTACK_SEARCH_URL = 'core:haystack_search'
INVITE_EMAIL_PREVIEW_URL = 'core:invite_email_preview'
PUBLICATIONS_URL = 'citation:publications'
PUBLICATION_DETAIL_URL = 'citation:publication_detail'
USER_PROFILE_URL = 'core:user_profile'
WORKFLOW_URL = 'core:curator_workflow'
SENT_INVITES_URL = 'core:send_invites'

GET_TAGS = list(Tag.objects.all().values_list('name'))
GET_PLATFORM = list(Platform.objects.all().values_list('name'))
GET_SPONSORS = list(Sponsor.objects.all().values_list('name'))
GET_MODEL_DOCUMENTATION = list(ModelDocumentation.objects.all().values_list('name'))
GET_STATUS = [s[0] for s in Publication.Status]
GET_AUTHOR = list(Author.objects.all().values_list('family_name'))
GET_JOURNAL = list(Container.objects.all().values_list('name'))
DEFAULT_ALPHABET = st.characters(whitelist_categories={'Lu', 'Ll', 'Lt', 'Lm', 'Lo'}, blacklist_characters='\x00')


def text(min_size=1, max_size=20):
    return st.text(alphabet=DEFAULT_ALPHABET, min_size=min_size, max_size=max_size)


GENRATE_PUBLICATION = models(Publication, container=models(Container),
                             title=text(),
                             added_by=models(User),
                             code_archive_url=st.text(),
                             url=st.text(), zotero_key=st.just(None))
GENERATE_NOTES = models(Note, added_by=models(User), zotero_key=st.just(None))


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
        self.without_login_and_with_login_test(USER_PROFILE_URL)

    @settings(max_examples=MAX_EXAMPLES, perform_health_check=False)
    @given(text(), text())
    def test_profile_update(self, first_name, last_name):
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

    @settings(max_examples=MAX_EXAMPLES, perform_health_check=False)
    @given(text(), text())
    def test_profile_invalid_email_update(self, first_name, last_name):
        url = self.reverse(USER_PROFILE_URL, query_parameters={'format': 'json'})
        self.login()
        response = self.post(url, {'first_name': first_name,
                                   'last_name': last_name,
                                   'username': self.user.username,
                                   'email': "user@comses.net"
                                   })
        # Updating email should return status code 400 - but for now we are ignoring it
        self.assertEqual(200, response.status_code)

    # Test for invalid update of username
    @settings(max_examples=MAX_EXAMPLES, perform_health_check=False)
    @given(text(), text(), text())
    def test_profile_invalid_update(self, first_name, last_name, username):
        url = self.reverse(USER_PROFILE_URL, query_parameters={'format': 'json'})
        self.login()
        response = self.post(url, {'first_name': first_name, 'last_name': last_name,
                                   'username': username})
        self.assertTrue(400, response.status_code)


class ContactAuthor(BaseTest):
    @settings(max_examples=MAX_EXAMPLES)
    @given(text(), text())
    def test_contact_author_with_and_without_query_parameters(self, sub, text):
        self.login()
        # If all valid fields
        if sub.strip() is not '' and text.strip() is not '':
            url = self.reverse(SENT_INVITES_URL, query_parameters={'format': 'json'})
            response = self.post(url, {'invitation_subject': sub,
                                       'invitation_text': text
                                       })
            self.assertEqual(200, response.status_code)
        else:
            # If it contains any Invalid Fields
            response = self.post(SENT_INVITES_URL)
            self.assertEqual(400, response.status_code)


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
    @settings(max_examples=MAX_EXAMPLES, perform_health_check=False)
    @given(GENRATE_PUBLICATION, text())
    def test_canonical_publication_detail_view(self, p, slug):
        self.logout()
        url = self.reverse(PUBLICATION_DETAIL_URL, kwargs={'pk': 999999})
        self.without_login_and_with_login_test(url, after_status=404)

        url = self.reverse(PUBLICATION_DETAIL_URL, kwargs={'pk': p.pk, 'slug': slug})
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

    # Test that publication detail is saved successfully or not
    @settings(max_examples=MAX_EXAMPLES, perform_health_check=False)
    @given(GENRATE_PUBLICATION, text(), st.sampled_from(GET_PLATFORM), st.sampled_from(GET_SPONSORS),
           st.sampled_from(GET_MODEL_DOCUMENTATION), st.sampled_from(GET_STATUS), GENERATE_NOTES, st.booleans(), text())
    def test_publication_detail_save_with_all_valid_fields(self, p, slug, platforms, sponsors, model_documentations,
                                                           status, notes,
                                                           flagged, first_name):
        self.login()
        url = self.reverse(PUBLICATION_DETAIL_URL, query_parameters={'format': 'json'},
                           kwargs={'pk': p.pk, 'slug': slug})
        response = self.put(url, json.dumps({'title': p.title,
                                             'assigned_curator': first_name, 'platforms': [{'name': platforms[0]}],
                                             'sponsors': [{'name': sponsors[0]}],
                                             'model_documentation': [],
                                             'flagged': flagged,
                                             'status': status,
                                             'contact_author_name': first_name,
                                             'contact_email': "user@comses.net",
                                             'note': []}), content_type="application/json")
        self.assertEqual(200, response.status_code)
        # Retrieving the data to verify
        publication = Publication.objects.get(pk=p.pk)
        sponsor = list(publication.sponsors.all().values_list('name'))
        platform = list(publication.platforms.all().values_list('name'))
        self.assertEquals(sponsor[0], sponsors)
        self.assertEquals(platform[0], platforms)
        self.assertEquals(publication.flagged, flagged)
        self.assertEquals(publication.status, status)
        self.assertEquals(publication.contact_author_name, first_name)
        self.assertEquals(publication.contact_email, "user@comses.net")


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

    # Testing randomized search for author, status, flagged and is_archived
    @settings(max_examples=MAX_EXAMPLES, perform_health_check=False)
    @given(st.sampled_from(GET_STATUS), st.sampled_from(GET_AUTHOR), st.booleans(), st.booleans())
    def test_search_with_randomized_query_parameters(self, status, author, flagged, is_archived):
        self.login()
        p = SearchQuerySet().filter(is_primary=True, date_published__gte='2014-01-01T00:00:00Z',
                                    date_published__lte='2014-01-11T00:00:00Z', flagged=flagged,
                                    is_archived=is_archived, authors=author[0], status=status).count()
        url = self.reverse(HAYSTACK_SEARCH_URL)
        response = self.client.get(
            url + "?q=&publication_start_date=1%2F1%2F2014&publication_end_date=1%2F11%2F2014&status=" + status + "&journal=&authors=" +
            author[0] + "&assigned_curator=&flagged=" + str(flagged) + "&is_archived=" + str(is_archived))
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

    @settings(max_examples=MAX_EXAMPLES)
    @given(text(), text(), text())
    def test_contact_info_with_randomized_valid_data(self, name, message, contact):
        url = self.reverse(
            CONTACT_US_URL, query_parameters={'format': 'json'})
        response = self.get(url)
        json_data = json.loads(response.data['json'])
        security_hash = json_data['security_hash']
        timestamp = float(json_data['timestamp'])

        # Test for all Valid Fields
        if name.strip() is not '' and message.strip() is not '':
            response = self.post(url, {'name': name,
                                       'email': "user@comses.net",
                                       'message': message,
                                       'timestamp': timestamp,
                                       'security_hash': security_hash,
                                       'contact_number': ''})
            self.assertEqual(200, response.status_code)
        else:
            # Test for any Invalid Fields
            response = self.post(url, {'name': name,
                                       'email': "user@comses.net",
                                       'message': message,
                                       'timestamp': timestamp,
                                       'security_hash': security_hash,
                                       'contact_number': contact})
            self.assertEqual(400, response.status_code)

    # Test for dummy timestamp and security hash
    @settings(max_examples=MAX_EXAMPLES)
    @given(text(), text(), text())
    def test_contact_info_with_invalid_data(self, name, message, contact):
        url = self.reverse(
            CONTACT_US_URL, query_parameters={'format': 'json'})
        response = self.get(url)
        json_data = json.loads(response.data['json'])
        security_hash = json_data['security_hash'] + 'Fake'
        timestamp = float(json_data['timestamp']) + 1
        response = self.post(url, {'name': name,
                                   'email': "user@comses.net",
                                   'message': message,
                                   'timestamp': timestamp,
                                   'security_hash': security_hash,
                                   'contact_number': contact})
        self.assertEqual(400, response.status_code)


class EmailPreviewTest(BaseTest):
    @settings(max_examples=MAX_EXAMPLES)
    @given(st.text(), st.text())
    def test_email_priview_with_and_without_query_parameters(self, sub, text):
        self.login()
        # If all the fields are valid
        if sub.strip() is not '' and text.strip() is not '':
            url = self.reverse(INVITE_EMAIL_PREVIEW_URL,
                               query_parameters={'invitation_subject': sub, 'invitation_text': text})
            response = self.get(url)
            self.assertEqual(200, response.status_code)
        else:
            # If any of the fields are Invalid
            response = self.get(INVITE_EMAIL_PREVIEW_URL)
            self.assertEqual(400, response.status_code)


class CuratorWorkflowTest(BaseTest):
    def test_edits(self):
        pass
