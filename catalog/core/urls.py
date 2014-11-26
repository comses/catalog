from django.conf.urls import patterns, include, url
from .views import dashboard, LoginView, LogoutView

urlpatterns = patterns('',
    url(r'^$', dashboard, name='dashboard'),
    url(r'^accounts/login/$', LoginView.as_view(), name='login'),
    url(r'^accounts/logout/$', LogoutView.as_view(), name='logout'),
)
