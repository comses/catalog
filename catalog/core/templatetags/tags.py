import re

from django import template
from django.core.exceptions import ValidationError
from django.template.loader import get_template

from citation.models import Author, Platform, Sponsor, Tag, Container

register = template.Library()


@register.filter(is_safe=True)
def active(request, pattern):
    return 'active' if pattern == request.path else ''


@register.filter(is_safe=True)
def active_re(request, pattern):
    return 'active' if re.search(pattern, request.path) else ''


@register.inclusion_tag('public/includes/pagination.html')
def pagination_control(paginator, current_page):
    return {'paginator': paginator, 'current_page': current_page}


@register.filter()
def list_authors(authors):
    if not authors:
        return 'Unknown'
    else:
        return ', '.join(a.name for a in authors)


@register.inclusion_tag('public/includes/facet_checkbox.html')
def facet_checkbox(instance):
    return {'name_attr': instance['id'],
            'id_attr': instance['id'],
            'name': instance['name'],
            'statistic': instance['publication_count']}


@register.filter()
def add_field_css(field, css_classes: str):
    if field.errors:
        css_classes += ' is-invalid'
    css_classes = field.css_classes(css_classes)
    deduped_css_classes = ' '.join(set(css_classes.split(' ')))
    return field.as_widget(attrs={'class': deduped_css_classes})


@register.simple_tag()
def top_categories_by_content_type(content_type, matches):
    context_list_name = content_type
    if content_type == Author._meta.verbose_name_plural:
        template = get_template('public/includes/author_search_results.html')
    elif content_type == Container._meta.verbose_name_plural:
        template = get_template('public/includes/container_search_results.html')
    elif content_type in [ct._meta.verbose_name_plural for ct in [Platform, Sponsor, Tag]]:
        template = get_template('public/includes/related_search_results.html')
        context_list_name = 'matches'
    else:
        raise ValidationError('Content Type {} not allowed'.format(content_type))
    return template.render({context_list_name: matches})
