from rest_framework import permissions

import logging

logger = logging.getLogger(__name__)


class CanViewReadOnlyOrEditPublication(permissions.IsAuthenticatedOrReadOnly):

    def has_object_permission(self, request, view, publication):
        user = request.user
        return (
            user.is_superuser or
            (publication.published and request.method in permissions.SAFE_METHODS) or
            (user.is_authenticated() and publication.is_editable_by(user))
        )
