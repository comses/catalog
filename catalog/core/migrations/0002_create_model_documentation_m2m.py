# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='publication',
            name='model_documentation_m2m',
            field=models.ManyToManyField(to='core.ModelDocumentation', blank=True),
        ),
    ]
