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
        parser.add_argument('-u', '--usernames',
                            required=True,
                            nargs='+',
                            help='List of space separated usernames to assign as curators to untagged publications')
        parser.add_argument('-N',
                            type=int,
                            help='Maximum number of untagged publications to assign')
        parser.add_argument('--verbose',
                            action='store_true')
        parser.add_argument('-s', '--status',
                            default='UNREVIEWED',
                            help='Filter by UNFLAGGED or FLAGGED status')

    @staticmethod
    def assign_publications(username, untagged_publication_ids, lower_bound, upper_bound, verbose, status):
        print("Giving user {} publications between {} and {} with status {}".format(username, lower_bound,
                                                                                    upper_bound - 1, status))
        user = User.objects.get(username=username)
        publications = models.Publication.objects.filter(id__in=untagged_publication_ids[lower_bound:upper_bound])
        Command.print_publications(publications, verbose)

        publications.update(assigned_curator=user)

    @staticmethod
    def print_publications(publications, verbose):
        if verbose:
            for publication in publications:
                print("\tID: {}, Title: {}, DOI: {}".format(publication.id, publication.title or None,
                                                            publication.doi or None))

    def handle(self, *args, **options):
        N = options['N']
        usernames = options['usernames']
        verbose = options['verbose']
        status = options['status']
        if status == 'UNREVIEWED':
            filter_expr = {'status': 'UNREVIEWED'}
        elif status == 'FLAGGED':
            filter_expr = {'flagged': True}
        else:
            raise ValueError('status can only be UNREVIEWED or FLAGGED')

        with transaction.atomic():
            untagged_publications = models.Publication.objects \
                                        .filter(assigned_curator__isnull=True, **filter_expr).order_by('id')[:N]
            Command.print_publications(untagged_publications, verbose)
            untagged_publication_ids = list(untagged_publications \
                                            .values_list('id', flat=True))

            untagged_publications_count = len(untagged_publication_ids)
            if untagged_publications_count == 0:
                raise ValueError('No publications found')
            n = untagged_publications_count // len(usernames)
            r = untagged_publications_count % len(usernames)

            first_username = usernames.pop()
            lower_bound = 0
            upper_bound = n + r
            self.assign_publications(first_username, untagged_publication_ids, lower_bound, upper_bound, verbose,
                                     status)

            for i in range(len(usernames)):
                username = usernames[i]
                lower_bound = n * (i + 1) + r
                upper_bound = n * (i + 2) + r

                self.assign_publications(username, untagged_publication_ids, lower_bound, upper_bound, verbose, status)

            update_index.Command().handle(noinput=True)
