import csv
from io import StringIO

from citation import models
from citation.export_data import CSV_DEFAULT_HEADER

from .common import BaseTest


class ExportDataViewTest(BaseTest):
    def test_export_streams_publication_data(self):
        container = self.create_container(name="Export Journal", issn="1234-5678")
        container.save()
        publication = self.create_publication(
            title="Publication included in export",
            added_by=self.user,
            container=container,
        )
        publication.save()
        author = models.Author.objects.create(
            given_name="Ada",
            family_name="Lovelace",
        )
        models.PublicationAuthors.objects.create(
            publication=publication,
            author=author,
            role=models.PublicationAuthors.RoleChoices.AUTHOR,
        )
        second_author = models.Author.objects.create(
            given_name="Alan",
            family_name="Turing",
        )
        models.PublicationAuthors.objects.create(
            publication=publication,
            author=second_author,
            role=models.PublicationAuthors.RoleChoices.AUTHOR,
        )

        response = self.get("core:export_data")
        content = b"".join(response.streaming_content).decode()
        rows = list(csv.reader(StringIO(content)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        header, row = rows
        self.assertEqual(header, CSV_DEFAULT_HEADER)
        self.assertEqual(row[header.index("title")], publication.title)
        self.assertEqual(
            row[header.index("author_names")], "Ada Lovelace; Alan Turing"
        )
        self.assertEqual(row[header.index("container__issn")], container.issn)
        self.assertEqual(row[header.index("container__name")], container.name)
