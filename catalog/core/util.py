import logging

logger = logging.getLogger(__name__)


def create_cas_user(tree):
    logger.debug("create_cas_user received tree %s", tree)


class RelationIdentifier():
    """
    Helper class to store the global default name for the visualization Identifier
    """
    JOURNAL ='Journal'
    SPONSOR = 'Sponsor'
    PLATFORM = 'Platform'
    AUTHOR = 'Author'
    GENERAL = 'General'
    MODELDOCUMENDTATION = 'Modeldoc'
