from rest_framework.urlpatterns import format_suffix_patterns
from django.conf.urls import include, url
from .views import index, LoginView, LogoutView, DashboardView, PublicationDetail, PublicationList

# API endpoints
urlpatterns = format_suffix_patterns([
    url(r'^publications/$', PublicationList.as_view(), name='publications'),
    url(r'^publications/(?P<pk>\d+)/$', PublicationDetail.as_view(), name='publication_detail'),
])

urlpatterns += [
    url(r'^$', index, name='index'),
    url(r'^search/$', include('haystack.urls')),
    url(r'^dashboard/$', DashboardView.as_view(), name='dashboard'),
    url(r'^accounts/login/$', LoginView.as_view(), name='login'),
    url(r'^accounts/logout/$', LogoutView.as_view(), name='logout'),
]
