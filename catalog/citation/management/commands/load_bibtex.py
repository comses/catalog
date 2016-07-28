from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth.models import User
import os

from ... import bibtex as bibtex_api

import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Loads bibtex data into the database"

    def add_arguments(self, parser):
        parser.add_argument('--file',
                            dest='file_name',
                            help='settings json file describing how you want to load into the db')
        parser.add_argument('--username',
                            dest='user_name',
                            help='username to load the data into the db as')

    def handle(self, *args, **options):
        file_name = options['file_name']
        if not os.path.exists(file_name):
            logger.error("Settings file '{}' does not exist".format(file_name))
        else:
            user_name = options['user_name']
            user = User.objects.get(username=user_name)
            bibtex_api.process_entries(file_name, user)