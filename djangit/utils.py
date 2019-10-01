import json
from collections import defaultdict
import datetime
import math


from django.forms import model_to_dict
from django.utils import timezone

def current_time():
  return timezone.now()

def full_group_by(l, key=lambda x: x):
  d = defaultdict(list)
  for item in l:
    d[key(item)].append(item)
  return d.items()

flatten = lambda l: [item for sublist in l for item in sublist]

def find(iterator, key):
  """
    returns first occurence of match or None
  """
  return next(filter(key, iterator) ,None)


def hash_for_string(str):
  # abs() because hash potentially returns negative int
  # [2:] because hex returns string starting in 0x 
  return hex(
    abs(
      hash(str)
    )
  )[2:]

def hash_for_model_instance(instance):
  """ returns a git-like hash-string for a model instance """

  
  # we exclude m2m because we want their 'versioning' to be updated independently 
  m2m_attrs =  [ f.attname for f in instance._meta.many_to_many ]
  inst_dict = {
    k: ( v.__str__() if isinstance(v, datetime.datetime) else v )
    for (k,v) in model_to_dict(instance).items()
    if k not in m2m_attrs
  }
  json_str = json.dumps(inst_dict, sort_keys=True)
  return hash_for_string(json_str)


class LockedInformationException(Exception):
  pass