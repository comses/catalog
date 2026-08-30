from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django_cas_ng import views as cas_ng_views

from catalog.core.views import LoginView

# Public URL paths/names are unchanged from the django-cas-client setup:
# 'cas_login' still lives at /cas/asu/login/ and 'logout' at /accounts/logout/,
# so templates, tests and CAS server registrations keep working.
urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', LoginView.as_view(), name='login'),
    path('cas/asu/login/', cas_ng_views.LoginView.as_view(), name='cas_login'),
    path('accounts/logout/', cas_ng_views.LogoutView.as_view(), name='logout'),
    path('accounts/password_change/', auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('accounts/password_reset_done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('api/', include('citation.urls')),
    path('', include('catalog.core.urls')),
]

if settings.DEBUG and 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns.insert(0, path('__debug__/', include(debug_toolbar.urls)))
