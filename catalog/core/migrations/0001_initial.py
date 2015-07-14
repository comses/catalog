# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Creator',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('creator_type', models.CharField(max_length=32, choices=[(b'AUTHOR', 'author'), (b'REVIEWED_AUTHOR', 'reviewed author'), (b'CONTRIBUTOR', 'contributor'), (b'EDITOR', 'editor'), (b'TRANSLATOR', 'translator'), (b'SERIES_EDITOR', 'series editor')])),
                ('first_name', models.CharField(max_length=255)),
                ('last_name', models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='InvitationEmailTemplate',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=32)),
                ('text', models.TextField()),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('last_modified', models.DateTimeField(auto_now=True)),
                ('added_by', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Journal',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=255)),
                ('url', models.URLField(max_length=255, null=True, blank=True)),
                ('abbreviation', models.CharField(max_length=255, blank=True)),
            ],
        ),
        migrations.CreateModel(
            name='ModelDocumentation',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='Note',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('text', models.TextField()),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('zotero_key', models.CharField(max_length=64, unique=True, null=True, blank=True)),
                ('zotero_date_added', models.DateTimeField(null=True, blank=True)),
                ('zotero_date_modified', models.DateTimeField(null=True, blank=True)),
                ('deleted_on', models.DateTimeField(null=True, blank=True)),
                ('added_by', models.ForeignKey(related_name='added_note_set', to=settings.AUTH_USER_MODEL)),
                ('deleted_by', models.ForeignKey(related_name='deleted_note_set', blank=True, to=settings.AUTH_USER_MODEL, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Platform',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=255)),
                ('url', models.URLField(null=True, blank=True)),
                ('description', models.TextField(null=True, blank=True)),
            ],
        ),
        migrations.CreateModel(
            name='PlatformVersion',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('version', models.TextField()),
                ('platform', models.ForeignKey(to='core.Platform')),
            ],
        ),
        migrations.CreateModel(
            name='Publication',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('title', models.TextField()),
                ('abstract', models.TextField(blank=True)),
                ('short_title', models.CharField(max_length=255, blank=True)),
                ('zotero_key', models.CharField(max_length=64, unique=True, null=True, blank=True)),
                ('url', models.URLField(null=True, blank=True)),
                ('date_published_text', models.CharField(max_length=32, blank=True)),
                ('date_published', models.DateField(null=True, blank=True)),
                ('date_accessed', models.DateField(null=True, blank=True)),
                ('archive', models.CharField(max_length=255, blank=True)),
                ('archive_location', models.CharField(max_length=255, blank=True)),
                ('library_catalog', models.CharField(max_length=255, blank=True)),
                ('call_number', models.CharField(max_length=255, blank=True)),
                ('rights', models.CharField(max_length=255, blank=True)),
                ('extra', models.TextField(blank=True)),
                ('published_language', models.CharField(default=b'English', max_length=255, blank=True)),
                ('zotero_date_added', models.DateTimeField(help_text='date added field from zotero', null=True, blank=True)),
                ('zotero_date_modified', models.DateTimeField(help_text='date modified field from zotero', null=True, blank=True)),
                ('code_archive_url', models.URLField(max_length=255, null=True, blank=True)),
                ('contact_author_name', models.CharField(max_length=255, blank=True)),
                ('contact_email', models.EmailField(max_length=254, blank=True)),
                ('status', models.CharField(default=b'UNTAGGED', max_length=32, choices=[(b'UNTAGGED', 'Not reviewed'), (b'NEEDS_AUTHOR_REVIEW', 'Curator has reviewed publication, requires author intervention.'), (b'FLAGGED', 'Flagged for further internal review by CoMSES staff'), (b'AUTHOR_UPDATED', 'Updated by author, needs CoMSES review'), (b'INVALID', 'Publication record is not applicable or invalid'), (b'COMPLETE', 'Reviewed and verified by CoMSES')])),
                ('date_added', models.DateTimeField(help_text='Date this publication was imported into this system', auto_now_add=True)),
                ('date_modified', models.DateTimeField(help_text='Date this publication was last modified on this system', auto_now=True)),
                ('author_comments', models.TextField(blank=True)),
                ('email_sent_count', models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='PublicationAuditLog',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('action', models.CharField(default=b'SYSTEM_LOG', max_length=32, choices=[(b'AUTHOR_EDIT', 'Author edit'), (b'SYSTEM_LOG', 'System log'), (b'CURATOR_EDIT', 'Curator edit')])),
                ('message', models.TextField(blank=True)),
                ('creator', models.ForeignKey(blank=True, to=settings.AUTH_USER_MODEL, help_text='The user who initiated this action, if any.', null=True)),
            ],
            options={
                'ordering': ['-date_added'],
            },
        ),
        migrations.CreateModel(
            name='Sponsor',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=255)),
                ('url', models.URLField(null=True, blank=True)),
                ('description', models.TextField(null=True, blank=True)),
            ],
        ),
        migrations.CreateModel(
            name='Tag',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(unique=True, max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='JournalArticle',
            fields=[
                ('publication_ptr', models.OneToOneField(parent_link=True, auto_created=True, primary_key=True, serialize=False, to='core.Publication')),
                ('pages', models.CharField(max_length=255, blank=True)),
                ('issn', models.CharField(max_length=255, blank=True)),
                ('volume', models.CharField(max_length=255, blank=True)),
                ('issue', models.CharField(max_length=255, blank=True)),
                ('series', models.CharField(max_length=255, blank=True)),
                ('series_title', models.CharField(max_length=255, blank=True)),
                ('series_text', models.CharField(max_length=255, blank=True)),
                ('doi', models.CharField(max_length=255, blank=True)),
                ('journal', models.ForeignKey(to='core.Journal')),
            ],
            bases=('core.publication',),
        ),
        migrations.AddField(
            model_name='publicationauditlog',
            name='publication',
            field=models.ForeignKey(related_name='audit_log_set', to='core.Publication'),
        ),
        migrations.AddField(
            model_name='publication',
            name='added_by',
            field=models.ForeignKey(related_name='added_publication_set', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='publication',
            name='assigned_curator',
            field=models.ForeignKey(related_name='assigned_publication_set', blank=True, to=settings.AUTH_USER_MODEL, help_text='Currently assigned curator', null=True),
        ),
        migrations.AddField(
            model_name='publication',
            name='creators',
            field=models.ManyToManyField(to='core.Creator'),
        ),
        migrations.AddField(
            model_name='publication',
            name='model_documentation',
            field=models.ForeignKey(blank=True, to='core.ModelDocumentation', null=True),
        ),
        migrations.AddField(
            model_name='publication',
            name='platforms',
            field=models.ManyToManyField(to='core.Platform', blank=True),
        ),
        migrations.AddField(
            model_name='publication',
            name='sponsors',
            field=models.ManyToManyField(to='core.Sponsor', blank=True),
        ),
        migrations.AddField(
            model_name='publication',
            name='tags',
            field=models.ManyToManyField(to='core.Tag', blank=True),
        ),
        migrations.AddField(
            model_name='note',
            name='publication',
            field=models.ForeignKey(blank=True, to='core.Publication', null=True),
        ),
    ]
