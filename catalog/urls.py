from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.contrib.auth import views as auth_views
from cas import views as cas_views
from django.urls import path

from catalog.core.views import LoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', LoginView.as_view(), name='login'),
    path('cas/asu/login/', cas_views.login, name='cas_login'),
    path('accounts/logout/', cas_views.logout, name='logout'),
    path('accounts/password_change/', auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('accounts/password_reset_done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('', include('citation.urls')),
    path('', include('catalog.core.urls')),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns.insert(0, path('__debug__/', include(debug_toolbar.urls)))