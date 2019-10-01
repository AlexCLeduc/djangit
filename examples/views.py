from django.shortcuts import render
from django.views import View
from django.urls import path
from django.views import generic

from examples.models import Commit, Division

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

urlpatterns = [
  path("commit/<int:commit_pk>/", ViewCommit.as_view(), name="view-commit"),
  path("commit/<int:commit_pk>/history/",GitLog.as_view(), name="git-log"),
  path("commit/<int:commit_pk>/<str:model>/<int:eternal_pk>/history/", GitLog.as_view(), name="git-object-log"),
]