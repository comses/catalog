from django.contrib import admin

from .models import Publication, Note, Tag, JournalArticle, Creator

admin.site.register(Publication)
admin.site.register(Note)
admin.site.register(Tag)
admin.site.register(JournalArticle)
admin.site.register(Creator)
