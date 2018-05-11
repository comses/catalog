from django import template
from citation.graphviz.globals import CacheNames
import re

register = template.Library()


@register.filter(is_safe=True)
def active(request, pattern):
    return 'active' if pattern == request.path else ''


@register.filter(is_safe=True)
def active_re(request, pattern):
    return 'active' if re.search(pattern, request.path) else ''


@register.filter
def get_item(dictionary, key):
    """Dictionary lookup"""
    return dictionary.get(CacheNames.CONTRIBUTION_DATA.value + str(key))

