from django.contrib.contenttypes.models import ContentType

from citation.models import Author, Submitter, SuggestedMerge

from .common import BaseTest


class SuggestedMergeListViewTest(BaseTest):
    def test_navigation_reaches_suggestions_after_the_first_page(self):
        creator, _ = Submitter.get_or_create(user=self.user, email=self.user.email)
        content_type = ContentType.objects.get_for_model(Author)
        for index in range(21):
            SuggestedMerge.objects.create(
                content_type=content_type, creator=creator, duplicates=[],
                new_content={'given_name': f'Author {index}', 'family_name': 'Example'},
            )

        first = self.get('core:public-merge-list')
        self.assertContains(first, 'Page 1 of 2.')
        self.assertContains(first, 'href="?page=2">next</a>')
        self.assertContains(first, 'href="?page=2">last &raquo;</a>')
        self.assertNotContains(first, '>previous</a>')
        self.assertEqual(len(first.context['suggested_merges']), 20)

        last = self.get('core:public-merge-list', {'page': 2})
        self.assertContains(last, 'Page 2 of 2.')
        self.assertContains(last, 'href="?page=1">previous</a>')
        self.assertNotContains(last, '>next</a>')
        self.assertEqual(len(last.context['suggested_merges']), 1)


class AutocompleteViewTest(BaseTest):
    def test_missing_model_name_returns_bad_request(self):
        response = self.get("core:autocomplete", {"search": "test"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Missing model_name query param"})

    def test_unsupported_model_name_returns_bad_request(self):
        response = self.get(
            "core:autocomplete", {"model_name": "publication", "search": "test"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Invalid model_name"})
