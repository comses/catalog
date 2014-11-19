from django.db import models

class Creator(models.Model):
    CREATOR_CHOICES = (
                ('AUTHOR', 'author'),
                ('REVIEWED_AUTHOR', 'reviewed author'),
                ('CONTRIBUTOR', 'contributor'),
                ('EDITOR', 'editor'),
                ('TRANSLATOR', 'translator'),
                ('SERIES_EDITOR', 'series editor'),
            )
    creator_type = models.CharField(choices=CREATOR_CHOICES, max_length=32)
    first_name = models.CharField(max_length=200)
    last_name = models.CharField(max_length=200)


class Tag(models.Model):
    name = models.CharField(max_length=100)
    tag_type = models.CharField(max_length=100)


class Note(models.Model):
    title = models.TextField()
    note = models.TextField()


class Publication(models.Model):
    title = models.TextField()
    abstract = models.TextField()
    short_title = models.CharField(max_length=200)
    url = models.URLField()
    date_published = models.DateTimeField()
    date_accessed = models.DateTimeField()
    archive = models.CharField(max_length=200)
    archive_location = models.CharField(max_length=200)
    library_catalog = models.CharField(max_length=200)
    call_number = models.PositiveIntegerField()
    rights = models.CharField(max_length=200)
    extra = models.TextField()
    tags = models.ManyToManyField('Tag')
    notes = models.ManyToManyField('Note')
    creators = models.ManyToManyField('Creator')
    published_language = models.CharField(max_length=200)
    added_by = models.ForeignKey('auth.User')
    date_added = models.DateTimeField()
    date_modified = models.DateTimeField()


class JournalArticle(Publication):
    publication = models.CharField(max_length=200)
    pages = models.PositiveIntegerField()
    issn = models.CharField(max_length=200)
    volume = models.PositiveIntegerField()
    issue = models.PositiveIntegerField()
    series = models.CharField(max_length=200)
    series_title = models.CharField(max_length=200)
    series_text = models.CharField(max_length=200)
    journal_abbr = models.CharField(max_length=200)
    doi = models.CharField(max_length=200)


class Book(Publication):
    series = models.CharField(max_length=200)
    series_number = models.PositiveIntegerField()
    volume = models.PositiveIntegerField()
    num_of_volume = models.PositiveIntegerField()
    edition = models.PositiveIntegerField()
    place = models.CharField(max_length=200)
    publisher = models.CharField(max_length=200)
    num_of_pages = models.PositiveIntegerField()
    isbn = models.CharField(max_length=200)


class Report(Publication):
    report_number = models.PositiveIntegerField()
    report_type = models.CharField(max_length=200)
    series_title = models.CharField(max_length=200)
    place = models.CharField(max_length=200)
    institution = models.CharField(max_length=200)
    pages = models.PositiveIntegerField()


class Thesis(Publication):
    thesis_type = models.CharField(max_length=200)
    university = models.CharField(max_length=200)
    place = models.CharField(max_length=200)
    num_of_pages = models.PositiveIntegerField()
