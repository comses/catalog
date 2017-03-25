from django.core.urlresolvers import reverse
from django.test import TestCase, Client
from django.utils.http import urlencode
from hypothesis import given, strategies as st, settings
from django.contrib.auth.models import User
from citation.models import Publication, Container
from hypothesis.extra.django.models import models


class ViewsTestCase(TestCase):
    PUBLIC_URLS = ['login', 'core:contact_us']
    PRIVATE_URLS = ['core:dashboard', 'core:haystack_search', 'citation:publications'
        , 'core:user_profile', 'core:curator_workflow', 'citation:publication_detail']

    def setUp(self):
        self.c = Client()

    def assert_redirect_to_page(self, page_reverse_string, redirect_reverse_string, next_in_url=True, **kwargs):
        response = self.c.get(self.reverse(page_reverse_string, kwargs=kwargs))
        redirect_url = reverse(redirect_reverse_string)
        if next_in_url:
            redirect_url += "?next=" + self.reverse(page_reverse_string, kwargs=kwargs)
        self.assertRedirects(response, redirect_url)

    def assert_200_response_code(self, page_reverse_string, **kwargs):
        url = self.reverse(page_reverse_string, kwargs=kwargs)
        response = self.c.get(url)
        self.assertEquals(response.status_code, 200)

    def assert_302_response_code(self, page_reverse_string, **kwargs):
        url = self.reverse(page_reverse_string, kwargs=kwargs)
        response = self.c.get(url)
        self.assertEquals(response.status_code, 302)

    def reverse(self, viewname, query_parameters=None, **kwargs):
        reversed_url = reverse(viewname, **kwargs)
        if query_parameters is not None:
            return '%s?%s' % (reversed_url, urlencode(query_parameters))
        return reversed_url


class AnonymousUserViewsTests(ViewsTestCase):
    @settings(max_examples=15)
    @given(url_name=st.sampled_from(ViewsTestCase.PUBLIC_URLS))
    def test_public_urls(self, url_name):
        self.assert_200_response_code(url_name)

    @settings(max_examples=15)
    @given(url_name=st.sampled_from(ViewsTestCase.PRIVATE_URLS))
    def test_private_urls(self, url_name):
        if url_name == "citation:publication_detail":
            self.assert_redirect_to_page(url_name, 'login', True, pk=1, slug='garbage')
        else:
            self.assert_redirect_to_page(url_name, 'login')


class LoggedInUserViewsTests(ViewsTestCase):
    def setUp(self):
        super(LoggedInUserViewsTests, self).setUp()
        self.user = User.objects.create_superuser(username='email@email.com', email='email@email.com',
                                                  password='password')
        self.c.login(username='email@email.com', password='password')

    @settings(max_examples=15)
    @given(url_name=st.sampled_from(ViewsTestCase.PUBLIC_URLS))
    def test_public_urls(self, url_name):
        self.assert_200_response_code(url_name)

    @settings(max_examples=15)
    @given(st.sampled_from(ViewsTestCase.PRIVATE_URLS))
    def test_public_urls(self, url_name):

        if url_name == "citation:publication_detail":
            p = models(Publication, container=models(Container),
                       added_by=models(User),
                       code_archive_url=st.text(),
                       url=st.text(), zotero_key=st.just(None)).example()
            self.assert_302_response_code(url_name, pk=p.pk, slug='garbage')
        else:
            self.assert_200_response_code(url_name)
