from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from datetime import datetime

from catalog.core.models import Publication

import unicodecsv as csv


class Command(BaseCommand):
    help = 'Exports data to a csv file'

    def find_max(self, attribute):
        return Publication.objects.annotate(num=Count(attribute)).order_by('-num')[0].num

    def get_attribute_headers(self, title, max_attribute):
        header = []
        for i in range(0, max_attribute):
            header.append(title + str(i+1))
        return header

    def get_attribute_values(self, attributes, max_value):
        c = []
        for attr in attributes:
            c.append(str(attr))
        if len(c) != max_value:
            c.append(" "* (max_value-len(c)))
        return c

    def handle(self, *args, **options):
        header = ["Publication Date", "Title", "Code Url", "Docs", "Primary Author"]
        max_platforms = self.find_max('platforms')
        max_sponsors = self.find_max('sponsors')

        header.extend(self.get_attribute_headers("Platform", max_platforms))
        header.extend(self.get_attribute_headers("Sponsor", max_sponsors))
        publications = Publication.objects.all().prefetch_related('creators', 'sponsors', 'platforms')

        with open('data.csv', 'wb') as csvfile:
            writer = csv.writer(csvfile, delimiter=',')
            writer.writerow(header)
            for pub in publications:
                row = [pub.date_published or pub.date_published_text, pub.title, pub.code_archive_url, str(pub.model_documentation), str(pub.creators.all()[0])]
                row.extend(self.get_attribute_values(pub.platforms.all(), max_platforms))
                row.extend(self.get_attribute_values(pub.sponsors.all(), max_sponsors))
                writer.writerow(row)

