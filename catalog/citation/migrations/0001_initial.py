# -*- coding: utf-8 -*-
# Generated by Django 1.9.9 on 2016-08-23 20:41
from __future__ import unicode_literals

from django.conf import settings
import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditCommand',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('AUTHOR_EDIT', 'Author edit'), ('SYSTEM_LOG', 'System log'), ('CURATOR_EDIT', 'Curator edit')], max_length=32)),
                ('action', models.CharField(choices=[('SPLIT', 'Split Record'), ('MERGE', 'Merge Records'), ('LOAD', 'Load from File'), ('MANUAL', 'User entered changes')], max_length=32)),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('message', models.TextField(blank=True, help_text='A human readable representation of the change made')),
                ('creator', models.ForeignKey(blank=True, help_text='The user who initiated this action, if any.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='citation_creator_set', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-date_added'],
            },
        ),
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('UPDATE', 'Update'), ('INSERT', 'Insert'), ('DELETE', 'Delete')], max_length=32)),
                ('row_id', models.BigIntegerField()),
                ('table', models.CharField(max_length=128)),
                ('payload', django.contrib.postgres.fields.jsonb.JSONField(blank=True, help_text='A JSON dictionary containing modified fields, if any, for the given publication', null=True)),
                ('audit_command', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='auditlogs', to='citation.AuditCommand')),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
        migrations.CreateModel(
            name='Author',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.TextField(choices=[('INDIVIDUAL', 'individual'), ('ORGANIZATION', 'organization')], max_length=32)),
                ('given_name', models.CharField(max_length=200)),
                ('family_name', models.CharField(max_length=200)),
                ('orcid', models.TextField(max_length=200)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('date_added', models.DateTimeField(auto_now_add=True, help_text='Date this model was imported into this system')),
                ('date_modified', models.DateTimeField(auto_now=True, help_text='Date this model was last modified on this system')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='AuthorAlias',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('given_name', models.CharField(max_length=200)),
                ('family_name', models.CharField(max_length=200)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='author_aliases', to='citation.Author')),
            ],
        ),
        migrations.CreateModel(
            name='Container',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('issn', models.TextField(blank=True, default='', max_length=500)),
                ('type', models.TextField(blank=True, default='', max_length=1000)),
                ('name', models.CharField(max_length=300)),
                ('date_added', models.DateTimeField(auto_now_add=True, help_text='Date this container was imported into this system')),
                ('date_modified', models.DateTimeField(auto_now=True, help_text='Date this container was last modified on this system')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='ContainerAlias',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.TextField(blank=True, default='', max_length=1000)),
                ('container', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='container_aliases', to='citation.Container')),
            ],
        ),
        migrations.CreateModel(
            name='InvitationEmailTemplate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=32)),
                ('text', models.TextField()),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('last_modified', models.DateTimeField(auto_now=True)),
                ('added_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='citation_added_by', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ModelDocumentation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('date_added', models.DateTimeField(auto_now_add=True, help_text='Date this model was imported into this system')),
                ('date_modified', models.DateTimeField(auto_now=True, help_text='Date this model was last modified on this system')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Note',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField()),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('zotero_key', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('zotero_date_added', models.DateTimeField(blank=True, null=True)),
                ('zotero_date_modified', models.DateTimeField(blank=True, null=True)),
                ('deleted_on', models.DateTimeField(blank=True, null=True)),
                ('added_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='citation_added_note_set', to=settings.AUTH_USER_MODEL)),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='citation_deleted_note_set', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Platform',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('url', models.URLField(blank=True, default='')),
                ('description', models.TextField(blank=True, default='')),
                ('date_added', models.DateTimeField(auto_now_add=True, help_text='Date this model was imported into this system')),
                ('date_modified', models.DateTimeField(auto_now=True, help_text='Date this model was last modified on this system')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Publication',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.TextField()),
                ('abstract', models.TextField(blank=True)),
                ('short_title', models.CharField(blank=True, max_length=255)),
                ('zotero_key', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('url', models.URLField(blank=True)),
                ('date_published_text', models.CharField(blank=True, max_length=32)),
                ('date_published', models.DateField(blank=True, null=True)),
                ('date_accessed', models.DateField(blank=True, null=True)),
                ('archive', models.CharField(blank=True, max_length=255)),
                ('archive_location', models.CharField(blank=True, max_length=255)),
                ('library_catalog', models.CharField(blank=True, max_length=255)),
                ('call_number', models.CharField(blank=True, max_length=255)),
                ('rights', models.CharField(blank=True, max_length=255)),
                ('extra', models.TextField(blank=True)),
                ('published_language', models.CharField(blank=True, default='English', max_length=255)),
                ('zotero_date_added', models.DateTimeField(blank=True, help_text='date added field from zotero', null=True)),
                ('zotero_date_modified', models.DateTimeField(blank=True, help_text='date modified field from zotero', null=True)),
                ('code_archive_url', models.URLField(blank=True, max_length=255)),
                ('contact_author_name', models.CharField(blank=True, max_length=255)),
                ('contact_email', models.EmailField(blank=True, max_length=254)),
                ('status', models.CharField(choices=[('UNTAGGED', 'Not reviewed'), ('NEEDS_AUTHOR_REVIEW', 'Curator has reviewed publication, requires author intervention.'), ('FLAGGED', 'Flagged for further internal review by CoMSES staff'), ('AUTHOR_UPDATED', 'Updated by author, needs CoMSES review'), ('INVALID', 'Publication record is not applicable or invalid'), ('COMPLETE', 'Reviewed and verified by CoMSES')], default='UNTAGGED', max_length=32)),
                ('date_added', models.DateTimeField(auto_now_add=True, help_text='Date this publication was imported into this system')),
                ('date_modified', models.DateTimeField(auto_now=True, help_text='Date this publication was last modified on this system')),
                ('author_comments', models.TextField(blank=True)),
                ('email_sent_count', models.PositiveIntegerField(default=0)),
                ('is_primary', models.BooleanField(default=True)),
                ('pages', models.CharField(blank=True, default='', max_length=255)),
                ('issn', models.CharField(blank=True, default='', max_length=255)),
                ('volume', models.CharField(blank=True, default='', max_length=255)),
                ('issue', models.CharField(blank=True, default='', max_length=255)),
                ('series', models.CharField(blank=True, default='', max_length=255)),
                ('series_title', models.CharField(blank=True, default='', max_length=255)),
                ('series_text', models.CharField(blank=True, default='', max_length=255)),
                ('doi', models.CharField(blank=True, default='', max_length=255)),
                ('added_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='citation_added_publication_set', to=settings.AUTH_USER_MODEL)),
                ('assigned_curator', models.ForeignKey(blank=True, help_text='Currently assigned curator', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='citation_assigned_publication_set', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='PublicationAuthors',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('AUTHOR', 'author'), ('REVIEWED_AUTHOR', 'reviewed author'), ('CONTRIBUTOR', 'contributor'), ('EDITOR', 'editor'), ('TRANSLATOR', 'translator'), ('SERIES_EDITOR', 'series editor')], max_length=32)),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_authors', to='citation.Author')),
                ('publication', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_authors', to='citation.Publication')),
            ],
        ),
        migrations.CreateModel(
            name='PublicationCitations',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('citation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_citations_referenced_by', to='citation.Publication')),
                ('publication', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_citations', to='citation.Publication')),
            ],
        ),
        migrations.CreateModel(
            name='PublicationModelDocumentations',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('model_documentation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_modeldocumentations', to='citation.ModelDocumentation')),
                ('publication', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_modeldocumentations', to='citation.Publication')),
            ],
        ),
        migrations.CreateModel(
            name='PublicationPlatforms',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('platform', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publications_platforms', to='citation.Platform')),
                ('publication', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_platforms', to='citation.Publication')),
            ],
        ),
        migrations.CreateModel(
            name='PublicationSponsors',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('publication', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_sponsors', to='citation.Publication')),
            ],
        ),
        migrations.CreateModel(
            name='PublicationTags',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('publication', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_tags', to='citation.Publication')),
            ],
        ),
        migrations.CreateModel(
            name='Raw',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.TextField(choices=[('BIBTEX_FILE', 'BibTeX File'), ('BIBTEX_ENTRY', 'BibTeX Entry'), ('BIBTEX_REF', 'BibTeX Reference'), ('CROSSREF_DOI_SUCCESS', 'CrossRef lookup succeeded'), ('CROSSREF_DOI_FAIL', 'CrossRef lookup failed'), ('CROSSREF_SEARCH_SUCCESS', 'CrossRef search succeeded'), ('CROSSREF_SEARCH_FAIL_NOT_UNIQUE', 'CrossRef search failed - not unique'), ('CROSSREF_SEARCH_FAIL_OTHER', 'CrossRef search failed - other'), ('CROSSREF_SEARCH_CANDIDATE', 'CrossRef search match candidate')], max_length=100)),
                ('value', django.contrib.postgres.fields.jsonb.JSONField()),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='RawAuthors',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_added', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='raw_authors', to='citation.Author')),
                ('raw', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='raw_authors', to='citation.Raw')),
            ],
        ),
        migrations.CreateModel(
            name='Sponsor',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('url', models.URLField(blank=True, default='')),
                ('description', models.TextField(blank=True, default='')),
                ('date_added', models.DateTimeField(auto_now_add=True, help_text='Date this model was imported into this system')),
                ('date_modified', models.DateTimeField(auto_now=True, help_text='Date this model was last modified on this system')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Tag',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('date_added', models.DateTimeField(auto_now_add=True, help_text='Date this model was imported into this system')),
                ('date_modified', models.DateTimeField(auto_now=True, help_text='Date this model was last modified on this system')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='raw',
            name='authors',
            field=models.ManyToManyField(related_name='raw', through='citation.RawAuthors', to='citation.Author'),
        ),
        migrations.AddField(
            model_name='raw',
            name='container',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='raw', to='citation.Container'),
        ),
        migrations.AddField(
            model_name='raw',
            name='publication',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='raw', to='citation.Publication'),
        ),
        migrations.AddField(
            model_name='publicationtags',
            name='tag',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_tags', to='citation.Tag'),
        ),
        migrations.AddField(
            model_name='publicationsponsors',
            name='sponsor',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publication_sponsors', to='citation.Sponsor'),
        ),
        migrations.AddField(
            model_name='publication',
            name='citations',
            field=models.ManyToManyField(related_name='referenced_by', through='citation.PublicationCitations', to='citation.Publication'),
        ),
        migrations.AddField(
            model_name='publication',
            name='container',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='citation.Container'),
        ),
        migrations.AddField(
            model_name='publication',
            name='creators',
            field=models.ManyToManyField(related_name='publications', through='citation.PublicationAuthors', to='citation.Author'),
        ),
        migrations.AddField(
            model_name='publication',
            name='model_documentation',
            field=models.ManyToManyField(blank=True, related_name='publications', through='citation.PublicationModelDocumentations', to='citation.ModelDocumentation'),
        ),
        migrations.AddField(
            model_name='publication',
            name='platforms',
            field=models.ManyToManyField(blank=True, related_name='publications', through='citation.PublicationPlatforms', to='citation.Platform'),
        ),
        migrations.AddField(
            model_name='publication',
            name='sponsors',
            field=models.ManyToManyField(blank=True, related_name='publications', through='citation.PublicationSponsors', to='citation.Sponsor'),
        ),
        migrations.AddField(
            model_name='publication',
            name='tags',
            field=models.ManyToManyField(blank=True, through='citation.PublicationTags', to='citation.Tag'),
        ),
        migrations.AddField(
            model_name='note',
            name='publication',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='citation.Publication'),
        ),
        migrations.AlterUniqueTogether(
            name='rawauthors',
            unique_together=set([('author', 'raw')]),
        ),
        migrations.AlterUniqueTogether(
            name='publicationtags',
            unique_together=set([('publication', 'tag')]),
        ),
        migrations.AlterUniqueTogether(
            name='publicationsponsors',
            unique_together=set([('publication', 'sponsor')]),
        ),
        migrations.AlterUniqueTogether(
            name='publicationplatforms',
            unique_together=set([('publication', 'platform')]),
        ),
        migrations.AlterUniqueTogether(
            name='publicationmodeldocumentations',
            unique_together=set([('publication', 'model_documentation')]),
        ),
        migrations.AlterUniqueTogether(
            name='publicationcitations',
            unique_together=set([('publication', 'citation')]),
        ),
        migrations.AlterUniqueTogether(
            name='publicationauthors',
            unique_together=set([('publication', 'author')]),
        ),
        migrations.AlterUniqueTogether(
            name='containeralias',
            unique_together=set([('container', 'name')]),
        ),
        migrations.AlterUniqueTogether(
            name='authoralias',
            unique_together=set([('author', 'given_name', 'family_name')]),
        ),
    ]