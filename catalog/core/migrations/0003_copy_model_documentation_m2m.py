# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


def copy_model_documentation(apps, schema_editor):
    Publication = apps.get_model('core', 'Publication')
    for publication in Publication.objects.all():
        if publication.model_documentation:
            publication.model_documentation_m2m.add(publication.model_documentation)
            publication.save()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_create_model_documentation_m2m'),
    ]

    operations = [
        migrations.RunPython(copy_model_documentation),
        migrations.RemoveField(
            model_name='publication',
            name='model_documentation',
        ),
    ]
