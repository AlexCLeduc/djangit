import uuid, json, datetime, types
from itertools import chain

from django.conf import settings
from django.db import models
from django.contrib import admin
from django.utils import timezone
from django.db.models.signals import pre_save, post_save, m2m_changed

from ..utils import (
  hash_for_string,
  LockedInformationException
)

# from .diffs import Diff, TagM2MDiff


def old_create_m2m_proxy_model(from_model, field):

  # note that field.related_model doesn't work because it's not attached yet when this runs
  related_model = field.target_field.model 
  m2m_field = models.ManyToManyField(
    related_model,
    related_name="+",    
  )

  proxy_model_attrs = dict(
    __module__=from_model.__module__,
    related_objects=m2m_field,
  )

  proxy_model = type(
    f"{from_model.__name__}_{field.name}_Proxy",
    (models.Model, ),
    proxy_model_attrs,
  )

  return proxy_model


def create_scalar_proxy_model(from_model,field):
  cloned_scalar_field = field.__class__(null=True)

  proxy_model = type(
    f"{from_model.__name__}_{field.name}_Proxy",
    (models.Model, ),
    dict(
      __module__=from_model.__module__,
      value=cloned_scalar_field,
    )
  )

  return proxy_model



def create_m2m_proxy_record(history_model, field_name, related_objects):
  proxy_model = history_model._meta.get_field(field_name).related_model
  new_proxy_record = proxy_model.objects.create()
  new_proxy_record.related_objects.add(*related_objects)
  return new_proxy_record

def create_scalar_proxy_record(history_model, field_name, value):
  proxy_model = history_model._meta.get_field(field_name).related_model
  new_proxy_record = proxy_model.objects.create(value=value)
  return new_proxy_record


def create_initial_version(saved_instance):
  # since no last-version exists, there is special stuff to be done

  model = saved_instance.__class__
  history_model = model._history_class

  version_dict = dict(
    eternal=saved_instance,
    previous_version=None,
  )

  m2m_fields = saved_instance._meta.many_to_many
  for f in m2m_fields:
    attr = f.name
    version_dict[attr] = create_m2m_proxy_record(history_model, attr, getattr(saved_instance, attr).all() )

  scalar_fields = [
    f for f in saved_instance._meta.fields
    if not isinstance(f, models.ForeignKey) and not f.primary_key
  ]
  for f in scalar_fields:
    attr = f.name
    version_dict[attr] = create_scalar_proxy_record(history_model,attr, getattr(saved_instance,attr) )
  fk_fields = [
    f for f in saved_instance._meta.fields
    if isinstance(f, models.ForeignKey)
  ]
  for f in fk_fields:
    version_dict[f.name] = getattr(saved_instance, f.name)

  history_model.objects.create(**version_dict)




def save_instance_and_create_version(saved_instance, last_ver):

  history_model = saved_instance._history_class
  version_dict = dict(
    eternal=saved_instance,
    previous_version=last_ver
  )

  
  for f in saved_instance._meta.many_to_many:
    attr = f.name
    inst_related_pks = set(obj.pk for obj in getattr(saved_instance, attr).all() )
    ver_related_pks = set(obj.pk for obj in getattr(last_ver, attr).related_objects.all() )

    if inst_related_pks == ver_related_pks:
      version_dict[attr] = getattr(last_ver, attr)
    else:
      version_dict[attr] = create_m2m_proxy_record(history_model, attr, getattr(saved_instance, attr).all() )


  scalar_fields = [ 
    f for f in saved_instance._meta.fields
    if not isinstance(f, models.ForeignKey) and not f.primary_key
  ]

  for f in scalar_fields:
    attr = f.name
    new_value = getattr(saved_instance, attr)
    if new_value == getattr(last_ver, attr).value:
      version_dict[attr] = last_ver[attr]
    else:
      version_dict[attr] = create_scalar_proxy_record(history_model, attr, new_value)
  
  fk_fields = [
    f for f in saved_instance._meta.fields
    if isinstance(f, models.ForeignKey)
  ]
  for f in fk_fields:
    version_dict[f.name] = getattr(saved_instance, f.name)
  

  new_version = last_ver.__class__.objects.create(**version_dict)

  return new_version


# versions without previous pointers
# how to we know whether large or m2m fields have changed
# versions are usually cloned from an old version
# normally they would not clone m2m, but because proxy models are FKs, we'd preserve the m2m linkage 
# trying to set the m2m (via custom method?) will create (if necessary) the right proxy record

# what should the field look like ?
#  tags = TrackedManyToMany(Tags)
# .tags => 
# 
"""
  @version_tracked...
  class MyModel(VersionParent...)
    tags = TrackedManyToManyField(TagVersionModel)
      => would expand to...
        1. creating a proxy model
          * with a m2m link to the TagVersionModel._eternal_cls
        2. returning a nullable ForeignKey field to the newly created proxy model 


  inst.tags => ForeignKey(MyModel_TagEternalModel_ManyToManyProxy)
  inst.tags.eternal_objects => Queryset
  inst.tags.eternal_ids => list of eternal pks from queryset above

"""

class HasManyToManyPointerFields():
  def set_m2m(self,fieldname,new_values):
    prev_pointer_obj = getattr(self,fieldname, None)
    if prev_pointer_obj:
      new_pointer_obj = prev_pointer_obj.create_if_new(new_values)
    else:
      pointer_model = self._meta.get_field(fieldname).related_model
      new_pointer_obj = pointer_model.create(new_values)
    
    if prev_pointer_obj != new_pointer_obj:
      setattr(self, fieldname, new_pointer_obj)
      self.save()
      


class PointerField(models.ForeignKey):
  # Purely here to distinguish pointer-fields from regular foreign-keys
  pass


class ManyToManyPointerBase(models.Model):
  """
    the m2m field will always be called related
  """

  class Meta:
    abstract=True

  @classmethod
  def create(cls,qs_or_id_list):
    new_obj = cls.objects.create()
    new_obj.related.set(qs_or_id_list)
    return new_obj
    
  
  def create_if_new(self, new_tags):
    """
      clones to new record if m2m relation is changing
    """
    if set(t.id for t in self.related.all()) != set(new_tags):
      return self.create(new_tags)

  checksum = models.CharField(null=True,max_length=100)

  def save(self,*args,**kwargs):
    if self.checksum:
      raise LockedInformationException("Cannot edit a version once it has been finalized and comitted")
    super().save(*args,**kwargs)

  def finalize(self):
    str_to_hash = str( sorted(t.id for t in self.related.all()) )
    self.checksum = hash_for_string(str_to_hash)
    super().save()


def create_m2m_pointer_model(to_version_model):
  return type(
    f"{to_version_model.__name__}_ManyToManyPointer",
    (ManyToManyPointerBase, ),
    dict(
      related=models.ManyToManyField(to_version_model._eternal_cls),
      __module__=to_version_model.__module__,
    )
  )

  