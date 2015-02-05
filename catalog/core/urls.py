from rest_framework.urlpatterns import format_suffix_patterns
from django.conf.urls import patterns, include, url

from .views import index, LoginView, LogoutView, DashboardView, PublicationDetail, PublicationList, EmailPreview
from .forms import DateRangeSearchForm

from haystack.views import SearchView

# API endpoints
urlpatterns = format_suffix_patterns([
    url(r'^publications/$', PublicationList.as_view(), name='publications'),
    url(r'^publications/(?P<pk>\d+)/$', PublicationDetail.as_view(), name='publication_detail'),
    url(r'^publication/email-preview/$', EmailPreview.as_view(), name='invite_email_preview'),
])

urlpatterns += [
    url(r'^$', index, name='index'),
    url(r'^dashboard/$', DashboardView.as_view(), name='dashboard'),
    url(r'^accounts/login/$', LoginView.as_view(), name='login'),
    url(r'^accounts/logout/$', LogoutView.as_view(), name='logout'),
]

urlpatterns += patterns('haystack.views',
    url(r'^search/$', SearchView(template='search/search.html', form_class= DateRangeSearchForm), name='haystack_search'),
)
