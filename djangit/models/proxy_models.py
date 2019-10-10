import uuid, json, datetime, types
from itertools import chain

from django.forms import ModelForm
from django.conf import settings
from django.db import models
from django.contrib import admin
from django.utils import timezone
from django.db.models.signals import pre_save, post_save, m2m_changed

from ..utils import (
  hash_for_string,
  LockedInformationException
)

class HasManyToManyPointerFields():
  def set_m2m(self,fieldname,new_values):
    prev_pointer_obj = getattr(self,fieldname, None)
    if prev_pointer_obj:
      new_pointer_obj = prev_pointer_obj.save_or_create(new_values)
    else:
      pointer_model = self._meta.get_field(fieldname).related_model
      new_pointer_obj = pointer_model.create(new_values)
    
    if prev_pointer_obj != new_pointer_obj:
      setattr(self, fieldname, new_pointer_obj)
      self.save()
    
    return new_pointer_obj


class PointerField(models.ForeignKey):
  def formfield(self,**kwargs):
    m2m_model_field = self.remote_field.model._meta.get_field('related')
    return m2m_model_field.formfield()

class ManyToManyPointerBase(models.Model):
  """
    the m2m field will always be called related
  """

  class Meta:
    abstract=True

  checksum = models.CharField(null=True,max_length=100)


  @classmethod
  def create(cls,qs_or_id_list):
    new_obj = cls.objects.create()
    new_obj.related.set(qs_or_id_list)
    return new_obj
    
  
  def save_or_create(self,new_related_ids,force_new=False):
    if set(t.id for t in self.related.all()) == set(new_related_ids):
      return self
      
    if self.checksum or force_new:
      new_inst = self.create(new_related_ids)
      return new_inst

    else: #modify in place
      self.related.set(new_related_ids)
      return self

    



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

  