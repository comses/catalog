from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _


class NonEmptyTextField(models.TextField):

    description = "An Unique Nullable ID field"

    def __init__(self, *args, **kwargs):
        kwargs['null'] = True
        super(NonEmptyTextField, self).__init__(*args, **kwargs)

    def get_db_prep_save(self, value, connection, prepared=False):
        value = super(NonEmptyTextField, self).get_db_prep_value(value, connection, prepared)
        if value == '':
            return None
        else:
            return value
