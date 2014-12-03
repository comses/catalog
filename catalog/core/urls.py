from django.conf.urls import patterns, include, url
from .views import index, LoginView, LogoutView, DashboardView, PublicationView

urlpatterns = patterns('',
    url(r'^$', index, name='index'),
    url(r'^search', include('haystack.urls')),
    url(r'^dashboard', DashboardView.as_view(), name='dashboard'),
    url(r'^publications', PublicationView.as_view(), name='publications'),

    url(r'^accounts/login/$', LoginView.as_view(), name='login'),
    url(r'^accounts/logout/$', LogoutView.as_view(), name='logout'),
)
