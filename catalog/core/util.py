from typing import Tuple
from unidecode import unidecode
import logging
import re
from django.db.models.aggregates import Aggregate

logger = logging.getLogger(__name__)


def create_cas_user(tree):
    logger.debug("create_cas_user received tree %s", tree)