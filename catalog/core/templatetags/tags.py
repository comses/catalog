from django import template
import re

register = template.Library()


@register.filter(is_safe=True)
def active(request, pattern):
    return 'active' if pattern == request.path else ''


@register.filter(is_safe=True)
def active_re(request, pattern):
    return 'active' if re.search(pattern, request.path) else ''


@register.filter
def addstr(arg1, arg2):
    """concatenate arg1 & arg2"""
    return str(arg1) + str(arg2)

