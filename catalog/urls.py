from django.conf.urls import include, url
from django.contrib import admin
from django.contrib.auth import views as auth_views

from .core.forms import CatalogAuthenticationForm

urlpatterns = [
    url(r'^admin/', include(admin.site.urls)),
    url(r'^accounts/login/$', auth_views.login,
        {
            'template_name': 'accounts/login.html',
            'authentication_form': CatalogAuthenticationForm,
        },
        name='login'),
    url(r'^accounts/logout/$', auth_views.logout, {'next_page': '/'}, name='logout'),
    url(r'^accounts/password_change/$', auth_views.password_change, name='password_change'),
    url(r'^accounts/password_change/done$', auth_views.password_change_done, name='password_change_done'),
    url(r'^accounts/password_reset/$', auth_views.password_reset, name='password_reset'),
    url(r'^accounts/password_reset_done/$', auth_views.password_reset_done, name='password_reset_done'),
    url(r'', include('catalog.citation.urls', namespace='citation')),
    url(r'', include('catalog.core.urls', namespace='core'))
]
