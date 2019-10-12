import uuid, json, datetime, types, copy
from itertools import chain

from django.conf import settings
from django.db.models.base import ModelBase
from django.db import models, transaction
from django.forms import (
  Form,
)
from django.forms.models import (
  ModelForm,
  model_to_dict,
  construct_instance,
  ValidationError,
  InlineForeignKeyField,
)
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
from .proxy_models import (
  ManyToManyPointerBase,
  m2m_pointer_model_factory,
  HasManyToManyPointerFields,
  PointerField,
  _RealPointerField,
)

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
      v.eternal if isinstance(v, VersionedModel) else v
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
            if isinstance(field, _RealPointerField):
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

class VersionMeta(ModelBase):
  """
    this meta does 3 primary thing

    1. it creates the eternal model class
    2. it registers the add and remove many-to-many relations against the commit model
    3. it maps 'fake' pointer fields used by consumers to and adds convenient accessors  
      * this also involves creating pointer-model classes
  """
  def __new__(cls, cls_name, bases, cls_attrs, **kwargs):

    # TODO: 
    # 1. check whether this works when there are pointer-fields in an abtract parent. 

    module = cls_attrs.get('__module__')
    commit_model = cls_attrs.get('commit_model')

    fake_pointer_fields = {
      attr_name : attr_value
      for (attr_name, attr_value) in cls_attrs.items()
      if isinstance(attr_value, PointerField)
    }

    #replace 'fake' pointer fields with the real foreign keys
    for (name, fake_field) in fake_pointer_fields.items():
      pointer_model = m2m_pointer_model_factory(fake_field.pointed_model)
      real_field = _RealPointerField(pointer_model, null=True, on_delete=models.SET_NULL)
      cls_attrs[name] = real_field


    #actually create the class:
    new_cls = super().__new__(cls, cls_name, bases, cls_attrs, **kwargs )


    if new_cls._meta.abstract:
      # we dont create eternal models or create any commit-relations for abstract classes
      return new_cls
    
    # create eternal model
    # eternal class' only purpose is to add an auto-incrementing unique 'eternal_id' value to each version table
    # it seems easier/more orm-friendly to create a model for it than to allow joins on an arbitrary int column and hook it up to a legit DB sequence
    eternal_cls = type(
      f"Eternal{cls_name}",
      (models.Model,),
      dict(
        # _version_class=version_model_cls,
        __module__=module,
      )
    )

    models.ForeignKey(
      eternal_cls,
      on_delete=models.CASCADE,
    ).contribute_to_class(new_cls,'eternal')
    new_cls._eternal_cls = eternal_cls
    eternal_cls._version_class = new_cls


    # add m2m : 'added in commits'
    models.ManyToManyField(
      new_cls,
      related_name=f"added_in"
    ).contribute_to_class(commit_model, commit_model._add_attr_name_for_version_cls(new_cls) )
      
    # add m2m : 'removed in commits'
    # note that we use the eternal one for removals
    models.ManyToManyField(
      eternal_cls,
      related_name="removed_in",
    ).contribute_to_class(commit_model, commit_model._rm_attr_name_for_version_cls(new_cls))

    commit_model.tracked_models[new_cls.__name__.lower()] = new_cls

    return new_cls



class VersionedModel(models.Model, HasManyToManyPointerFields, metaclass=VersionMeta):
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

  def save_or_create(self,force_new=False):
    if self.checksum or force_new:
      new_inst = self.clone()
      new_inst.save()
      return new_inst
    else:
      self.save()
      return self

  
class VersionModelForm(ModelForm):

  def __init__(self,*args,initial=None,**kwargs):
    instance = kwargs['instance']
    # TODO: filter out fields that are excluded
    self._pointer_fields = [ f for f in instance._meta.get_fields() if isinstance(f, _RealPointerField) ]
    self._initial_pointer_values = { #store now to ensure they don't get overwritten by form
      f.name : getattr(instance, f.name)
      for f in self._pointer_fields
    }
    pointer_initials = {
      f.name : model_to_dict( getattr(instance, f.name) )['related']
      for f in self._pointer_fields
      if getattr(instance, f.name)
    }
    if initial:
      pointer_initials.update(initial)
    super().__init__(*args,initial=pointer_initials,**kwargs)


  def _post_clean(self):
    # TODO: find a way to not copy-paste and override private method...
    # the only we change is excluding pointer-fields from validation
    opts = self._meta

    exclude = self._get_validation_exclusions() + [f.name for f in self._pointer_fields ]

    # Foreign Keys being used to represent inline relationships
    # are excluded from basic field value validation. This is for two
    # reasons: firstly, the value may not be supplied (#12507; the
    # case of providing new values to the admin); secondly the
    # object being referred to may not yet fully exist (#12749).
    # However, these fields *must* be included in uniqueness checks,
    # so this can't be part of _get_validation_exclusions().
    for name, field in self.fields.items():
      if isinstance(field, InlineForeignKeyField):
        exclude.append(name)

    try:
      construct_excludes = opts.exclude + exclude if opts.exclude else exclude
      self.instance = construct_instance(self, self.instance, opts.fields, construct_excludes)
    except ValidationError as e:
      self._update_errors(e)

    try:
      self.instance.full_clean(exclude=exclude, validate_unique=False)
    except ValidationError as e:
      self._update_errors(e)

    # Validate uniqueness if needed.
    if self._validate_unique:
      self.validate_unique()

  def save(self,*args,**kwargs):
    with transaction.atomic():

      # at this point, _post_clean has written form-data onto self.instance

      for f in self._pointer_fields:
        if self.data[f.name]:

          new_data = self.data[f.name]

          existing_pointer_record = self._initial_pointer_values[f.name]
          if existing_pointer_record:
            new_pointer_record = existing_pointer_record.save_or_create(new_data)
          else:
            # started from empty relation, create new pointer
            pointer_model = f.related_model
            new_pointer_record = pointer_model.create(new_data)

        else:
          # form was submitted with empty m2m set
          # VersionModel's represent empty relations by a null pointer record
          new_pointer_record = None
        
        setattr(self.instance, f.name, new_pointer_record)


      possibly_new_instance = self.instance.save_or_create()
      return possibly_new_instance
  

