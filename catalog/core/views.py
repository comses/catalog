from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.generic import FormView, TemplateView
from django.utils.decorators import method_decorator
from django.core.urlresolvers import reverse

from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework.response import Response

import django_tables2 as tables
from django_tables2.utils import A

from .forms import LoginForm, PublicationDetailForm, JournalArticleDetailForm, DateRangeSearchForm
from .models import Publication, JournalArticle
from .serializers import PublicationSerializer


class LoginRequiredMixin(object):
    @classmethod
    def as_view(cls, **initkwargs):
        view = super(LoginRequiredMixin, cls).as_view(**initkwargs)
        return login_required(view)


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


def index(request):
    return render(request, 'index.html', {})


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"


class PublicationTable(tables.Table):
    title = tables.LinkColumn('publication_detail', args=[A('pk')])
    class Meta:
        model = Publication
        """ Fields to display in the Publication table """
        fields = ('title', 'status')


class PublicationList(LoginRequiredMixin, APIView):
    """
    List all publications, or create a new publication.
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get(self, request, format=None):
        publications = Publication.objects.all()
        if request.accepted_renderer.format == 'html':
            t = PublicationTable(publications)
            tables.RequestConfig(request, paginate={"per_page": 15}).configure(t)
            return Response({'table': t}, template_name="publications.html")

        serializer = PublicationSerializer(publications, many=True)
        return Response(serializer.data)


class PublicationDetail(LoginRequiredMixin, APIView):
    """
    Retrieve, update or delete a publication instance.
    """
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer)

    def get_object(self, pk):
        try:
            return Publication.objects.get_subclass(pk=pk)
        except Publication.DoesNotExist:
            raise Http404

    def get(self, request, pk, format=None):
        publication = self.get_object(pk)
        if request.accepted_renderer.format == 'html':
            if isinstance(publication, JournalArticle):
                form = JournalArticleDetailForm(instance=publication)
            else:
                form = PublicationDetailForm(instance=publication)

            data = {'form': form}
            return Response(data, template_name='publication_detail.html')

        serializer = PublicationSerializer(publication)
        return Response(serializer.data)

    def put(self, request, pk, format=None):
        publication = self.get_object(pk)
        serializer = PublicationSerializer(publication, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        publication = self.get_object(pk)
        publication.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
