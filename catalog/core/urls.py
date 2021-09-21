from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns
from django.conf.urls import url, include
from django.views.generic import RedirectView, TemplateView

from . import views

app_name = 'core'

# non django rest framework endpoints for authentication, user dashboard, workflow, and search URLs
curator_urls = [
    url(r'^contact-us/$', views.ContactFormView.as_view(), name='contact_us'),
    url(r'^$', TemplateView.as_view(template_name='index.html'), name='index'),
    url(r'^dashboard/$', views.DashboardView.as_view(), name='dashboard'),
    url(r'^accounts/profile/$', views.UserProfileView.as_view(), name='user_profile'),
    url(r'^bug-report/$', RedirectView.as_view(url='https://gitreports.com/issue/comses/catalog', permanent=False),
        name='report_issues'),
    url(r'^github/$', RedirectView.as_view(url='https://github.com/comses/catalog', permanent=False), name='github'),
    url(r'^publication/workflow/$', views.CuratorWorkflowView.as_view(), name='curator_workflow'),
    url(r'^contact-authors/$', views.ContactAuthorsView.as_view(), name='contact_authors'),
    url(r'^search/$', views.CatalogSearchView.as_view(), name='haystack_search'),
    url(r'^search/platform/$', views.PlatformSearchView.as_view(), name="platform_search"),
    url(r'^search/sponsor/$', views.SponsorSearchView.as_view(), name="sponsor_search"),
    url(r'^search/tag/$', views.TagSearchView.as_view(), name="tag_search"),
    url(r'^search/journal/$', views.JournalSearchView.as_view(), name="journal_search"),
    url(r'^search/model-documentation/$', views.ModelDocumentationSearchView.as_view(),
        name="model_documentation_search"),
    url(r'^export/$', views.export_data, name="export_data"),
]

urlpatterns = [
    path('curator/', include(curator_urls)),
    path('visualization/', views.public_visualization_view, name='public-visualization'),
    path('publications/', views.public_search_view, name='public-search'),
    path('publications/add/', views.suggest_a_publication, name='suggest-a-publication'),
    path('publications/<int:pk>/', views.PublicationDetailView.as_view(), name='public-publication-detail'),
    path('merges/', views.suggested_merge_list_view, name='public-merge-list'),
    path('merges/create/', views.SuggestedMergeView.as_view(), name='public-merge'),
    path('autocomplete/', views.autocomplete, name='autocomplete'),
    path('', views.public_home, name='public-home'),
]
