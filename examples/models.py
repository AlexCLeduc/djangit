from django.db import models
from djangit.models.commit import create_version_parent, CommitBase, create_versioning_decorator, PointerField


class Commit(CommitBase):
  message = models.TextField(
    default="",
  )


version_model = create_version_parent(Commit)
add_versioning = create_versioning_decorator(Commit)



@add_versioning(create_m2m_pointer=True)
class Tag(version_model):
  name = models.TextField()

@add_versioning()
class Division(version_model):
  name = models.TextField()
  tags = PointerField(Tag._m2m_pointer_model, null=True, on_delete=models.SET_NULL)

@add_versioning()
class Team(version_model):
  name = models.TextField()
  division = models.ForeignKey(
    "examples.EternalDivision",
    null=False,
    on_delete=models.PROTECT
  )
  tags = PointerField(Tag._m2m_pointer_model, null=True, on_delete=models.SET_NULL)

@add_versioning
class Employee(version_model):
  name=models.TextField()
  team = models.ForeignKey(
    "examples.Team",
    null=False,
    related_name="employees",
    on_delete=models.PROTECT,
  )
  tags = PointerField(Tag._m2m_pointer_model, null=True, on_delete=models.SET_NULL)
