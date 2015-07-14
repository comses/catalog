# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_copy_model_documentation_m2m'),
    ]

    operations = [
        migrations.RenameField(model_name='publication',
                               old_name='model_documentation_m2m',
                               new_name='model_documentation')
    ]
