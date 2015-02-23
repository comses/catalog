from rest_framework.urlpatterns import format_suffix_patterns
from django.conf.urls import patterns, url, include
from django.contrib.auth.decorators import login_required

from .views import (IndexView, LoginView, LogoutView, DashboardView, PublicationDetail,
                    PublicationList, EmailPreview, ContactAuthor, ArchivePublication, CustomSearchView)

from .forms import CustomSearchForm

# API endpoints
urlpatterns = format_suffix_patterns([
    url(r'^publications/$', PublicationList.as_view(), name='publications'),
    url(r'^publications/(?P<pk>\d+)/$', PublicationDetail.as_view(), name='publication_detail'),
    url(r'^publications/email-preview/$', EmailPreview.as_view(), name='invite_email_preview'),
    url(r'^publications/invite/$', ContactAuthor.as_view(), name='send_invites'),
    url(r'^publications/archive/(?P<token>[\w:-]+)/$', ArchivePublication.as_view(), name='publication_archive'),
])

urlpatterns += [
    url(r'^$', IndexView.as_view(), name='index'),
    url(r'^dashboard/$', DashboardView.as_view(), name='dashboard'),
    url(r'^accounts/login/$', LoginView.as_view(), name='login'),
    url(r'^accounts/logout/$', LogoutView.as_view(), name='logout'),
]

urlpatterns += patterns('haystack.views',
    url(r'^search/$', login_required(CustomSearchView(form_class = CustomSearchForm)), name='haystack_search'),
)
