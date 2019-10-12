from django import template
from django.db.models import CharField, TextField, ForeignKey
from django.template.defaultfilters import date

from django_template_block_args import register_composed_template_with_blockargs

from djangit.models import _RealPointerField

from ..models import Commit


register = template.Library()

def get_field_display(obj,field):
  if isinstance(field, _RealPointerField) and getattr(obj,field.name):
    return ",".join( obj.__str__() for obj in getattr(obj,field.name).related.all() )
  if isinstance(field, ForeignKey):
    val = getattr(obj,field.name,None)
    if val:
      return val.__dict__
    else:
      return None
  if isinstance(field, (CharField,TextField) ):
    return getattr(obj,field.name)
  else:
    return getattr(obj,field.name)


# TODO: un-generalize this into model-specific 'detail' components
@register.inclusion_tag("object_table.html")
def object_table(obj):
  model = obj.__class__
  return {
    "model_name": getattr(model,"verbose_name",model._meta.label),
    "headers_and_values": [
      (field.verbose_name, get_field_display(obj,field) )
      for field in model._meta.fields
      if not field.name == "eternal"
    ]
  }



@register_composed_template_with_blockargs(
  register,
  'form-field.html',
  block_names=(
    "field_header",
    "field_input",
  )
)
def standard_form_field(field_id=None):
  return {
    "field_id": field_id,
  }
