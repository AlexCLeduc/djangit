import uuid, json, datetime, types
from itertools import chain

from django.conf import settings
from django.db import models, transaction
from django.forms import ModelForm
from django.contrib import admin
from django.utils import timezone
from django.db.models.signals import pre_save, post_save, m2m_changed

from ..diffs import Diff, TagM2MDiff
from ..utils import (
  full_group_by,
  hash_for_model_instance,
  hash_for_string,
  flatten,
  find,
  current_time,
  LockedInformationException
)
from .proxy_models import ManyToManyPointerBase, create_m2m_pointer_model, HasManyToManyPointerFields, PointerField

class CommitBase(models.Model):
  tracked_models = {}
  
  class Meta:
    abstract=True
    ordering = [ 'committed_at' ]

  checksum = models.CharField(
    null=True,
    max_length=100,
  )

  committed_at = models.DateTimeField(
    null=True
  )

  # TODO: allow merge commits by making this m2m
  parent_commit = models.ForeignKey(
    'self',
    null=True,
    on_delete=models.SET_NULL,
    related_name="children_commits",
  )
  time = models.DateTimeField(
    default=timezone.now,
    null=True,
  )

  def _add_versions(self,versions):
    by_class = full_group_by(versions, lambda v: v.__class__) 
    for (cls,v_list) in by_class:
      field_attr  = self._add_attr_name_for_version_cls(cls)

      getattr(self, field_attr).set(v_list)

  def _remove_objects(self,versions_or_eternals):
    """
      populates the removes_{model_label} dict appropriately
      versions is a list of versions OR their eternal objects
    """
    eternals = [
      v.eternal if isinstance(v, VersionBase) else v
      for v in versions_or_eternals
    ]
    by_class = full_group_by(eternals, lambda e: e._version_class)
    for (cls,e_list) in by_class:
      getattr(self, self._rm_attr_name_for_version_cls(cls) ).set(e_list)
    

  def _versions_added_for_class(self,v_cls):
    return list(getattr(self, self._add_attr_name_for_version_cls(v_cls) ).all())

  @property
  def _versions_added_by_class(self):
    return {
      cls: self._versions_added_for_class(cls)
      for (name,cls) in self.tracked_models.items()
    }

  @property
  def _removed_by_eternal_id(self):
    return {
      cls: list(getattr(self, self._rm_attr_name_for_version_cls(cls)).all())
      for (name,cls) in self.tracked_models.items()
    }
  def version_sets(self):
    
    # TODO: change data-structure to avoid separate query per ancestor
    versions_added = { **self._versions_added_by_class }

    removed_eternal_ids = { **self._removed_by_eternal_id }

    if self.parent_commit is None:
      return versions_added
    else:
      parent_versions = self.parent_commit.version_sets()
      versions = {
        cls: set( versions_added[cls] ) - set ( parent_versions[cls] )
        for cls in self.tracked_models.values()
      }

      versions_with_remove_applied = {
        cls: [ v for v in versions[cls] if v.eternal_id not in removed_eternal_ids ]
        for cls in self.tracked_models.values()
      }
      return versions_with_remove_applied

  def _compute_hash(self):

    hash_for_added = "".join(
      "".join(v.checksum for v in vlist)
      for vlist in self._versions_added_by_class.values()
    )

    if self.parent_commit:
      parent_checksum = self.parent_commit.checksum
      if not parent_checksum:
        raise Exception("Parent commit needs to be comitted")
    else:
      parent_checksum = ""

    return hash_for_string( hash_for_added + parent_checksum )


  def save(self,*args,**kwargs):
    if self.checksum:
        raise LockedInformationException("Cannot save a finalized commit")

    super().save(*args,**kwargs)  

  def commit(self):
    with transaction.atomic():
      self._finalize_versions()
      self.checksum = self._compute_hash()
      self.committed_at = current_time()
      super().save()

  @staticmethod
  def _add_attr_name_for_version_cls(cls):
    return f"adds_{cls.__name__.lower()}"
  
  @staticmethod
  def _rm_attr_name_for_version_cls(cls):
    return f"removes_{cls.__name__.lower()}"

  def _finalize_versions(self):
    for versions in self._versions_added_by_class.values():
      for v in versions:
        if not v.checksum:
          v.finalize_version()
          for field in v._meta.fields:
            if isinstance(field, PointerField):
              pointer = getattr(v,field.name)
              if pointer and not pointer.checksum:
                pointer.finalize()

  def ancestors(self):
    """
      returns in reverse-generational order 
    """
    if not self.parent_commit:
      return []
    
    return [ self.parent_commit, *self.parent_commit.ancestors() ]

  def descendants(self):
    """
      returns in children in depth-first order, nodes comes before their own descendants
    """
    children = list( self.__class__.objects.filter(parent_commit=self) )

    if not children:
      return []


    return flatten([
      [ child, *child.descendants() ]
      for child in children
    ])

  def version_for(self,eternal):
    version_cls = eternal._version_class
    
    # if this commit removed this object, then it has no version of this object
    if eternal in getattr(self, self._rm_attr_name_for_version_cls(version_cls) ).all():
      return None
    
    # if this commit added a version of this obj, then that version is the relevant version
    versions_added_for_this_cls = self._versions_added_for_class(version_cls)
    v = find(versions_added_for_this_cls, lambda v:v.eternal==eternal)
    if v:
      return v
    
    # if this commit didn't remove/add the object object, than its parent's version can be no less relevant
    if self.parent_commit:
      return self.parent_commit.version_for(eternal)
    
    return None
    
  def relevant_history_with_respect_to(self,eternal):
    """
      returns that modify (or remove) an object
      includes self, if relevant
    """
    v_cls = eternal._version_class
    add_attr = self._add_attr_name_for_version_cls(v_cls)
    rm_attr = self._rm_attr_name_for_version_cls(v_cls)
    relevant_commits = [
      c for c in [ self, *self.ancestors() ]
      if (
        eternal in [ added.eternal for added in getattr(c, add_attr).all() ] or
        eternal in getattr(c,rm_attr).all()
      )
    ]
    return relevant_commits



class VersionBase(models.Model):
  class Meta:
    abstract = True

  checksum = models.CharField(null=True,max_length=100)

  @classmethod
  def create_initial(cls,**attrs):
    eternal = cls._eternal_cls.objects.create()
    return cls.objects.create(
      eternal=eternal,
      **attrs,
    )


  def clone(self):
    """returns unsaved child version that can be saved"""
    # TODO: how should clones inherit and get cloned m2m linkages?
    import copy
    clone = copy.copy(self)
    clone.checksum=None
    clone.pk = None
    return clone

  
  
  def save(self,*args,**kwargs):
    # TODO: add way to recompute checksums in case of a data-migration

    if self.checksum:
      raise LockedInformationException("Cannot edit a version once it has been finalized and comitted")
    
    
    super().save(*args,**kwargs)

  def finalize_version(self):
    self.checksum = hash_for_model_instance(self)
    super().save()
  



def create_version_parent(commit_model=None):
  """
    creates the abstract version model that all version classes must inherit from
  """
  if not commit_model:
    raise Exception("must provide commit_model kwarg")


  class Meta:
    abstract=True

  cls_attrs = dict(
    __module__=commit_model.__module__,
    _comit_model=commit_model,
    Meta=Meta,
  )

  cls = type(
    f"{commit_model.__name__}Version",
    (VersionBase, HasManyToManyPointerFields),
    cls_attrs,
  )

  return cls

"""

  TODO:

  - helpful constraint utils
    - e.g. emulating a 1-1 or 1-many relationship on a per-commit basis
      - an employee 



  generating eternal tables ??

    - only purpose is to play well with django
      - uses DB sequences out of the box
      - versions have FKs to eternal tables
    - can be created via sub-class hook of ParentVersion

"""

def create_versioning_decorator(commitModel):
  def _add_versioning(create_m2m_pointer=False):
    def wrapped(version_model_cls):
      # eternal class' only purpose is to add an auto-incrementing unique 'eternal_id' value to each version table
      # it seems easier/more orm-friendly to create a model for it than to allow joins on an arbitrary int column and hook it up to a legit DB sequence
      eternal_cls = type(
        f"Eternal{version_model_cls.__name__}",
        (models.Model,),
        dict(
          _version_class=version_model_cls,
          __module__=version_model_cls.__module__,
        )
      )

      version_model_cls._eternal_cls = eternal_cls
      
      models.ForeignKey(
        eternal_cls,
        on_delete=models.CASCADE,
      ).contribute_to_class(version_model_cls,'eternal')

      # add m2m : 'added in commits'
      models.ManyToManyField(
        version_model_cls,
        related_name=f"added_in"
      ).contribute_to_class(commitModel, commitModel._add_attr_name_for_version_cls(version_model_cls) )
      
      # add m2m : 'removed in commits'
      # note that we use the eternal one for removals
      models.ManyToManyField(
        eternal_cls,
        related_name="removed_in",
      ).contribute_to_class(commitModel, commitModel._rm_attr_name_for_version_cls(version_model_cls))

      commitModel.tracked_models[version_model_cls.__name__.lower()] = version_model_cls

      if create_m2m_pointer:
        version_model_cls._m2m_pointer_model = create_m2m_pointer_model(version_model_cls)


      return version_model_cls
    
    return wrapped
  return _add_versioning