from django.conf.urls import include, url
from django.contrib import admin
from django.contrib.auth import views as auth_views
from cas import views as cas_views

from catalog.core.views import LoginView

urlpatterns = [
    url(r'^admin/', admin.site.urls),
    url(r'^accounts/login/$', LoginView.as_view(), name='login'),
    url(r'^cas/asu/login/$', cas_views.login, name='cas_login'),
    url(r'^accounts/logout/$', cas_views.logout, name='logout'),
    url(r'^accounts/password_change/$', auth_views.PasswordChangeView.as_view(), name='password_change'),
    url(r'^accounts/password_change/done$', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    url(r'^accounts/password_reset/$', auth_views.PasswordResetView.as_view(), name='password_reset'),
    url(r'^accounts/password_reset_done/$', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    url(r'^', include('citation.urls')),
    url(r'', include('catalog.core.urls')),
]
