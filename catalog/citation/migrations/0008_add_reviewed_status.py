# -*- coding: utf-8 -*-
# Generated by Django 1.10.1 on 2016-09-26 18:53
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('citation', '0007_update_publication_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='publication',
            name='status',
            field=models.CharField(choices=[('UNREVIEWED', 'Not reviewed: Has not been reviewed by CoMSES'), ('AUTHOR_UPDATED', 'Updated by author: Awaiting CoMSES review'), ('INVALID', 'Not applicable: Publication does not refer to a specific computational model'), ('REVIEWED', 'Reviewed: Publication metadata reviewed and verified by CoMSES')], default='UNREVIEWED', max_length=64),
        ),
    ]
