from django.shortcuts import render
from django.http.response import HttpResponseRedirect
from django.views import View
from django.views import generic
from django.urls import path, reverse

from djangit.models.commit import VersionBase, VersionModelForm

from .models import (
  Commit,
  Division,
)

# Create your views here.


class GitLog(generic.ListView):
  template_name = "git-log.html"
  def get_queryset(self):
    import IPython; IPython.embed()

class ViewCommit(generic.DetailView):
  template_name="commit_detail.html"
  def get_object(self):
    return Commit.objects.get(pk=self.kwargs['commit_pk'])

  def get_context_data(self,*args,**kwargs):
    ret = {
      **super().get_context_data(*args,**kwargs),
      "versions":self.object.version_sets,
    }
    return ret


class GitObjectLog(generic.ListView):
  template_name = "commit-view.html"
  def get_queryset(self,commit_pk):
    import IPython; IPython.embed()


class DivisionVersionForm(VersionModelForm):
  class Meta:
    model= Division
    fields= [
      'name',
      'tags',
    ]


class EditDivision(generic.FormView):
  template_name="edit.html"
  form_class = DivisionVersionForm
  def get_form_kwargs(self,*args,**kwargs):
    division = Division.objects.get(pk=self.kwargs.get("division_pk"))
    return { 
      **super().get_form_kwargs(*args,**kwargs),
      "instance": division,
    }

  def form_valid(self,form):
    possibly_new_inst = form.save()
    return HttpResponseRedirect( reverse('add-division-version', args=( possibly_new_inst.pk, )))
    


urlpatterns = [
  path("commit/<int:commit_pk>/", ViewCommit.as_view(), name="view-commit"),
  path("commit/<int:commit_pk>/history/",GitLog.as_view(), name="git-log"),
  path("commit/<int:commit_pk>/<str:model>/<int:eternal_pk>/history/", GitLog.as_view(), name="git-object-log"),
  path("add_version/division/<int:division_pk>",EditDivision.as_view(),name="add-division-version"),
]