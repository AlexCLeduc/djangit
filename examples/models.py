from django.db import models
# from djangit.models.commit import create_version_parent, CommitBase, create_versioning_decorator, PointerField
from djangit.models.commit import VersionedModel, CommitBase, PointerField


class Commit(CommitBase):
  message = models.TextField(
    default="",
  )


# version_model = create_version_parent(Commit)
# add_versioning = create_versioning_decorator(Commit)



class Tag(models.Model):
  name = models.TextField()

  def __str__(self):
    return self.name  

class Division(VersionedModel):
  commit_model=Commit
  name = models.TextField()
  tags = PointerField(Tag)

  def __str__(self):
    return self.name

class Team(VersionedModel):
  commit_model=Commit
  name = models.TextField()
  division = models.ForeignKey(
    "examples.EternalDivision",
    null=False,
    on_delete=models.PROTECT
  )
  tags = PointerField(Tag)


  def __str__(self):
    return self.name

class Employee(VersionedModel):
  commit_model=Commit
  name=models.TextField()
  team = models.ForeignKey(
    "examples.Team",
    null=False,
    related_name="employees",
    on_delete=models.PROTECT,
  )
  tags = PointerField(Tag)


  def __str__(self):
    return self.name