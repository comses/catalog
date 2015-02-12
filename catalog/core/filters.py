from .models import Publication

import django_filters

class BooleanFilter(django_filters.BooleanFilter):

    def filter(self, qs, value):
        if value is True:
            return qs.exclude(**{self.name+"__exact": ''})
        elif value is False:
            return qs.filter(**{self.name+"__exact": ''})
        return qs


class PublicationFilter(django_filters.FilterSet):
    contact_email = BooleanFilter()

    def __init__(self, *args, **kwargs):
        super(PublicationFilter, self).__init__(*args, **kwargs)

        for name, field in self.filters.iteritems():
            if isinstance(field, django_filters.ChoiceFilter):
                # Add "Any" entry to choice fields.
                field.extra['choices'] = tuple([("", "Any"), ] + list(field.extra['choices']))

    class Meta:
        model = Publication
        """ Fields by which user can filter the publications """
        fields = {'status': ['exact'], 'email_sent_count': ['gte']}

