from django.contrib.auth.models import User
from django.contrib import admin
from django.contrib.admin.helpers import ActionForm
from django import forms

from .models import AuditCommand, Publication, Note, Tag, Author, Sponsor, Platform, Container, ModelDocumentation
from .search_indexes import PublicationIndex


def assign_curator(modeladmin, request, queryset):
    assigned_curator_id = request.POST['assigned_curator_id']

    user = request.user
    audit_command = AuditCommand(creator=user, action=AuditCommand.Action.MANUAL)

    # Does not seem to be a Haystack method to update records based on a queryset so records are updated one at a time
    # to keep the Solr index in sync
    for publication in queryset:
        publication.log_update(audit_command=audit_command, assigned_curator_id=assigned_curator_id)


assign_curator.short_description = 'Assign Curator to Publications'


class PublicationCuractorForm(ActionForm):
    assigned_curator_id = forms.ModelChoiceField(queryset=User.objects.all(), label='User Name')


class PublicationAdmin(admin.ModelAdmin):
    list_filter = ('assigned_curator', 'is_primary')
    action_form = PublicationCuractorForm
    actions = [assign_curator]


admin.site.register(Publication, PublicationAdmin)
admin.site.register(Note)
admin.site.register(Tag)
admin.site.register(Author)
admin.site.register(Sponsor)
admin.site.register(Platform)
admin.site.register(Container)
admin.site.register(ModelDocumentation)
