from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import FormView, TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth import login, logout
from django.core.urlresolvers import reverse

from .forms import LoginForm
from .models import Publication

from django_tables2 import Table, SingleTableView

import django_filters


class LoginRequiredMixin(object):
    @classmethod
    def as_view(cls, **initkwargs):
        view = super(LoginRequiredMixin, cls).as_view(**initkwargs)
        return login_required(view)


def index(request):
    return render(request, 'index.html', {})


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"


class LoginView(FormView):
    form_class = LoginForm
    template_name = 'accounts/login.html'

    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def dispatch(self, *args, **kwargs):
        return super(LoginView, self).dispatch(*args, **kwargs)

    def form_valid(self, form):
        login(self.request, form.get_user())
        return super(LoginView, self).form_valid(form)

    def get_success_url(self):
        next_url = self.request.GET.get('next', '')
        # if no next_url specified, redirect to index (dashboard page).
        return next_url if next_url else reverse('dashboard')


class LogoutView(TemplateView):

    def get(self, request, *args, **kwargs):
        user = request.user
        logout(request)
        return redirect('login')


class PublicationTable(Table):
    class Meta:
        model = Publication
        fields = ('title', 'added_by', 'date_published')


class PublicationView(LoginRequiredMixin, SingleTableView):
    template_name = "publications.html"
    model = Publication
    table_class = PublicationTable

