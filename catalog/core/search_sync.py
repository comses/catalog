from django.dispatch import receiver

from citation.signals import publications_changed

from .search_indexes import refresh_search_documents


@receiver(publications_changed, dispatch_uid='catalog_refresh_search_documents')
def refresh_changed_publications(sender, publication_ids, related_ids=(), **kwargs):
    refresh_search_documents(
        sender=sender,
        publication_ids=publication_ids,
        related_ids=related_ids,
    )
