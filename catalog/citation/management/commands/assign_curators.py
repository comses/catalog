from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

from ... import models
from haystack.management.commands import update_index


class Command(BaseCommand):
    help = "Assign curators to untagged publications"

    def add_arguments(self, parser):
        parser.add_argument('--usernames',
                            required=True,
                            nargs='+',
                            help='List of space separated usernames to assign as curators to untagged publications')
        parser.add_argument('--N',
                            type=int,
                            help='Maximum number of untagged publications to assign')
        parser.add_argument('--verbose',
                            action='store_true')

    @staticmethod
    def assign_publications(username, untagged_publication_ids, lower_bound, upper_bound, verbose):
        print("Giving user {} publications between {} and {}".format(username, lower_bound, upper_bound-1))
        user = User.objects.get(username=username)
        publications = models.Publication.objects.filter(id__in=untagged_publication_ids[lower_bound:upper_bound])
        Command.print_publications(publications, verbose)

        publications.update(assigned_curator=user)

    @staticmethod
    def print_publications(publications, verbose):
        if verbose:
            for publication in publications:
                print("\t{}".format(publication.title))

    def handle(self, *args, **options):
        N = options['N']
        usernames = options['usernames']
        verbose = options['verbose']

        with transaction.atomic():
            untagged_publications = models.Publication.objects\
                .filter(assigned_curator__isnull=True, status='UNTAGGED')[:N]
            Command.print_publications(untagged_publications, verbose)
            untagged_publication_ids = list(untagged_publications\
                .values_list('id', flat=True))

            untagged_publications_count = len(untagged_publication_ids)
            if untagged_publications_count == 0:
                raise ValueError('No publications found')
            n = untagged_publications_count // len(usernames)
            r = untagged_publications_count % len(usernames)

            first_username = usernames.pop()
            lower_bound = 0
            upper_bound = n+r
            self.assign_publications(first_username, untagged_publication_ids, lower_bound, upper_bound, verbose)

            for i in range(len(usernames)):
                username = usernames[i]
                lower_bound = n*(i+1)+r
                upperbound = n*(i+2)+r

                self.assign_publications(username, untagged_publication_ids, lower_bound, upperbound, verbose)

            rebuild_index.Command().handle(noinput=True)