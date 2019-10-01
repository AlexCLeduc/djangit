from django.db import transaction

from tests.create_data import create_data

def run():
  with transaction.atomic():
    create_data()


