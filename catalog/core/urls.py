from django.urls import include, path
from rest_framework.urlpatterns import format_suffix_patterns
from django.views.generic import RedirectView, TemplateView

from . import views

app_name = 'core'

# non django rest framework endpoints for authentication, user dashboard, workflow, and search URLs
curator_urls = [
    path('contact-us/', views.ContactFormView.as_view(), name='contact_us'),
    path('', TemplateView.as_view(template_name='index.html'), name='index'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('accounts/profile/', views.UserProfileView.as_view(), name='user_profile'),
    path('bug-report/', RedirectView.as_view(url='https://gitreports.com/issue/comses/catalog', permanent=False),
        name='report_issues'),
    path('github/', RedirectView.as_view(url='https://github.com/comses/catalog', permanent=False), name='github'),
    path('publication/workflow/', views.CuratorWorkflowView.as_view(), name='curator_workflow'),
    path('contact-authors/', views.ContactAuthorsView.as_view(), name='contact_authors'),
    path('search/', views.CatalogSearchView.as_view(), name='haystack_search'),
    path('search/platform/', views.PlatformSearchView.as_view(), name="platform_search"),
    path('search/sponsor/', views.SponsorSearchView.as_view(), name="sponsor_search"),
    path('search/tag/', views.TagSearchView.as_view(), name="tag_search"),
    path('search/journal/', views.JournalSearchView.as_view(), name="journal_search"),
    path('search/model-documentation/', views.ModelDocumentationSearchView.as_view(),
        name="model_documentation_search"),
    path('export/', views.export_data, name="export_data"),
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
