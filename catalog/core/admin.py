from django.contrib import admin

from .models import Publication, Note, Tag, JournalArticle, Creator, Sponsor, Platform, Journal, ModelDocumentation

admin.site.register(Publication)
admin.site.register(Note)
admin.site.register(Tag)
admin.site.register(JournalArticle)
admin.site.register(Creator)
admin.site.register(Sponsor)
admin.site.register(Platform)
admin.site.register(Journal)
admin.site.register(ModelDocumentation)
