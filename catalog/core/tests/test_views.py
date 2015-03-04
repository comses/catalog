from .common import BaseTest

class ViewAccessTest(BaseTest):

    def test_login(self):
        response = self.get(self.login_url)
        self.assertTrue(200, response.status_code)

        response = self.post(self.login_url, {'username':'temporary', 'password':'temporary'})
        self.assertTrue(200, response.status_code)

    def test_logout(self):
        response = self.get(self.reverse('logout'))
        self.assertTrue(302, response.status_code)

    def without_login_and_with_login_test(self, url, before_status=302, after_status=200):
        response = self.get(url)
        self.assertEqual(before_status, response.status_code)
        if before_status is not 200:
            self.assertTrue(self.login_url in response['Location'])

        self.login()
        response = self.get(url)
        self.assertEqual(after_status, response.status_code)

    def test_index_view(self):
        self.without_login_and_with_login_test(self.reverse('login'), before_status=200)

    def test_dashboard_view(self):
        self.without_login_and_with_login_test(self.reverse('dashboard'))

    def test_publications_view(self):
        url = self.reverse('publications')
        self.without_login_and_with_login_test(url)

        response = self.get(url + "?page=-1")
        self.assertEqual(200, response.status_code)

        response = self.get(url + "?page=-1")
        self.assertEqual(200, response.status_code)

    def test_search_view(self):
        self.without_login_and_with_login_test(self.reverse('haystack_search'))

    def test_contact_view(self):
        self.without_login_and_with_login_test(self.reverse('contact_us'), before_status=200)
