from django.contrib.auth.models import User
from django.contrib import admin
from django.contrib.admin.helpers import ActionForm
from django import forms
from django.utils.translation import ugettext_lazy as _
from .models import AuditCommand, Publication, Note, Tag, Author, Sponsor, Platform, Container, ModelDocumentation
from .search_indexes import PublicationIndex

class PublicationStatusListFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = _('status')
    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        return (tuple([(s[0], s[0]) for s in Publication.Status]))

    def queryset(self, request, queryset):
        if self.value() in Publication.Status:
            return queryset.filter(status=self.value())
        else:
            return queryset.all()

def assign_curator(modeladmin, request, queryset):
    assigned_curator_id = request.POST['assigned_curator_id']

    user = request.user
    audit_command = AuditCommand(creator=user, action=AuditCommand.Action.MANUAL)

    # Does not seem to be a Haystack method to update records based on a queryset so records are updated one at a time
    # to keep the Solr index in sync
    for publication in queryset:
        publication.log_update(audit_command=audit_command, assigned_curator_id=assigned_curator_id)

assign_curator.short_description = 'Assign Curator to Publications'

class PublicationCuratorForm(ActionForm):
    assigned_curator_id = forms.ModelChoiceField(queryset=User.objects.filter(is_active=True), label='User Name')

class PublicationAdmin(admin.ModelAdmin):
    list_filter = ('assigned_curator', 'is_primary', PublicationStatusListFilter)
    action_form = PublicationCuratorForm
    actions = [assign_curator]

admin.site.register(Publication, PublicationAdmin)
admin.site.register(Note)
admin.site.register(Tag)
admin.site.register(Author)
admin.site.register(Sponsor)
admin.site.register(Platform)
admin.site.register(Container)
admin.site.register(ModelDocumentation)
