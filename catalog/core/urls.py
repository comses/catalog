from rest_framework.urlpatterns import format_suffix_patterns
from django.conf.urls import url
from django.contrib.auth.decorators import login_required
from django.views.generic import RedirectView, TemplateView

from .views import (LoginView, LogoutView, DashboardView, PublicationDetail, PublicationList, EmailPreview,
                    ContactAuthor, ArchivePublication, CustomSearchView, ContactUsView, UserProfileView, PlatformSearchView,
                    SponsorSearchView, TagSearchView, JournalSearchView, ModelDocSearchView)

from .forms import CustomSearchForm

# API endpoints
urlpatterns = format_suffix_patterns([
    url(r'^publication/$', PublicationList.as_view(), name='publications'),
    url(r'^publication/(?P<pk>\d+)/$', PublicationDetail.as_view(), name='publication_detail'),
    url(r'^publication/email-preview/$', EmailPreview.as_view(), name='invite_email_preview'),
    url(r'^publication/invite/$', ContactAuthor.as_view(), name='send_invites'),
    url(r'^publication/archive/(?P<token>[\w:-]+)/$', ArchivePublication.as_view(), name='publication_archive'),
    url(r'^contact/$', ContactUsView.as_view(), name='contact_us'),
    url(r'^accounts/profile/$', UserProfileView.as_view(), name='user_profile'),
])

urlpatterns += [
    url(r'^$', TemplateView.as_view(template_name='index.html'), name='index'),
    url(r'^dashboard/$', DashboardView.as_view(), name='dashboard'),
    url(r'^accounts/login/$', LoginView.as_view(), name='login'),
    url(r'^accounts/logout/$', LogoutView.as_view(), name='logout'),
    url(r'^bug-report/$', RedirectView.as_view(url='https://github.com/comses/catalog/issues/new'),
        name='report_issues')
]
urlpatterns += [
    url(r'^search/$', login_required(CustomSearchView(form_class=CustomSearchForm)), name='haystack_search'),
    url(r'^search/platform/$', PlatformSearchView.as_view(), name="platform-search"),
    url(r'^search/sponsor/$', SponsorSearchView.as_view(), name="sponsor-search"),
    url(r'^search/tag/$', TagSearchView.as_view(), name="tag-search"),
    url(r'^search/journal/$', JournalSearchView.as_view(), name="journal-search"),
    url(r'^search/modeldoc/$', ModelDocSearchView.as_view(), name="model-doc-search"),
]
