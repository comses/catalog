from django.contrib import admin

from .models import Publication, Note, Tag, Author, Sponsor, Platform, Container, ModelDocumentation

admin.site.register(Publication)
admin.site.register(Note)
admin.site.register(Tag)
admin.site.register(Author)
admin.site.register(Sponsor)
admin.site.register(Platform)
admin.site.register(Container)
admin.site.register(ModelDocumentation)
