from unittest import skip

from django.test import TestCase


from .create_data import create_data
from examples.models import Division, Team, Tag, Employee, Commit
from djangit.utils import LockedInformationException


def get_refreshed(model_inst):
  # refresh_from_db() does not work properly on instance that are copied, it impacts copies/originals and populates false data
  return model_inst.__class__.objects.get(pk=model_inst.pk)


class BasicTestCase(TestCase):

  # @classmethod
  # def setUpTestData(cls):
  #   create_data()


  def test_commit(self):
    c0 = Commit.objects.create()

    division_v0 = Division.create_initial(
      name="division1",
    )
    division_v1 = division_v0.clone()

    c0._add_versions([division_v0])
    c0.commit()
    
    c0.refresh_from_db()
    self.assertTrue(c0.checksum)
    
    division_v0.refresh_from_db()
    self.assertTrue(division_v0.checksum)


    division_v1.name="division one"
    division_v1.save()


    # modifying v1 should not modify v0
    division_v0.refresh_from_db()
    self.assertEqual(division_v0.name, "division1")


    
    t1 =  Tag.objects.create(name="category 1")
    t2 = Tag.objects.create(name="category 2")
    division2_v0 = Division.create_initial(
      name="division 2",
    )
    division3_v0 = Division.create_initial(
      name="division 3",
    )
    division3_v0.set_m2m('tags', [t1.id,t2.id])

    division3_v0.refresh_from_db()
    self.assertTrue(division3_v0.tags)
    self.assertEqual(
      set(division3_v0.tags.related.all()),
      set([t1,t2])
    )

    c1 = Commit.objects.create(parent_commit=c0)
    c1._add_versions([ division_v1 ])
    c1.commit()

    with self.assertRaises(LockedInformationException):
      c1.save()
    
    with self.assertRaises(LockedInformationException):
      division_v1.refresh_from_db()
      division_v1.save()
    
    
    c2 = Commit.objects.create(parent_commit=c1)
    c2._add_versions([division2_v0, division3_v0])
    c2._remove_objects([division_v0.eternal])
    c2.commit()



    # branch off c1 w/ out the removal
    c2_b = Commit.objects.create(parent_commit=c1)
    c2_b._add_versions([division2_v0, division3_v0])
    c2_b.commit()


    # make sure .commit() finalized the m2m pointer record
    division3_v0.tags.refresh_from_db()

    pointer = division3_v0.tags
    self.assertTrue(pointer.checksum)
    with self.assertRaises(LockedInformationException):
      pointer.save()


    self.assertEqual(c0.ancestors(), [])
    self.assertEqual(c1.ancestors(), [c0] )
    self.assertEqual(c2.ancestors(), [c1,c0])
    

    self.assertEqual(c0.descendants(), [c1,c2, c2_b])
    self.assertEqual(c1.descendants(), [c2, c2_b] )
    self.assertEqual(c2.descendants(), [])



    self.assertEqual(c0.version_for(division_v0.eternal), division_v0)
    self.assertEqual(c1.version_for(division_v1.eternal), division_v1)
    self.assertEqual(c2.version_for(division_v1.eternal), None)

    self.assertEqual(c2_b.version_for(division_v1.eternal), division_v1)

    self.assertEqual(
      c2.relevant_history_with_respect_to(division3_v0.eternal),
      [c2]
    )

    self.assertEqual(
      c2_b.relevant_history_with_respect_to(division_v0.eternal),
      [c1,c0]
    )

  def test_save_or_create(self):

    c0 = Commit.objects.create()

    division_v0 = Division.create_initial(
      name="division1",
    )
    
    c0._add_versions([division_v0])
    c0.commit()
    division_v0.refresh_from_db()
    c0.refresh_from_db()


    division_v0.name="division one"
    division_v1 = division_v0.save_or_create()

    division_v0.refresh_from_db()

    self.assertEqual(division_v0.name,"division1")
    self.assertEqual(division_v1.name,"division one")
    self.assertNotEqual(division_v1.pk, division_v0.pk)
    self.assertEqual(division_v0.eternal, division_v1.eternal)


  def test_form(self):
    from examples.views import DivisionVersionForm

    division = Division.create_initial(
      name="my division"
    )
    t1 = Tag.objects.create(name="cat1")
    t2 = Tag.objects.create(name="cat2")
    t3 = Tag.objects.create(name="cat3")

    division.set_m2m('tags', [t1.id])

    initial_pointer = division.tags

    f = DivisionVersionForm(instance=division)
    self.assertEqual(f.initial, {
      'name':'my division',
      'tags': [t1],
    })
    data = {
      'name': 'my new division',
      'tags': [t1.id, t2.id],
    }
    f_w_data = DivisionVersionForm(data, instance=division)
    f_w_data.is_valid()
    not_a_new_instance = f_w_data.save()
    
    not_a_new_instance = get_refreshed(not_a_new_instance)
    
    self.assertEqual(not_a_new_instance, division)
    self.assertEqual(not_a_new_instance.name, "my new division")
    self.assertEqual(
      set(t.id for t in not_a_new_instance.tags.related.all()),
      set([t1.id, t2.id])
    )

    c = Commit.objects.create()
    c._add_versions([not_a_new_instance])
    c.commit()


    not_a_new_instance= get_refreshed(not_a_new_instance)
    another_form = DivisionVersionForm({
      'name':'even newer division name',
      'tags':[t3.id],
    },instance=not_a_new_instance)
    another_form.is_valid()
    should_be_brand_new = another_form.save()

    should_be_brand_new = get_refreshed(should_be_brand_new)
    not_a_new_instance = get_refreshed(not_a_new_instance)

    self.assertNotEqual(should_be_brand_new, not_a_new_instance)
    self.assertNotEqual(should_be_brand_new.tags, not_a_new_instance.tags)
    self.assertEqual(
      [t.id for t in should_be_brand_new.tags.related.all()],
      [t3.id] 
    )
    self.assertEqual(should_be_brand_new.name,"even newer division name")


  def test_version_set(self):
    c = Commit.objects.create()

    self.assertEqual(c.version_sets(), {
      Tag: {},
      Division: {},
      Team: {},
    })

    division1_v0 = Division.create_initial(name="division1")
    c._add_versions([division1_v0])
    c = get_refreshed(c)
    self.assertEqual(c.version_sets(), {
      Tag: {},
      Division: { division1_v0.eternal_id : division1_v0 },
      Team: {},
    })


    division1_v1 = division1_v0.clone()
    division1_v1.name="division one"
    division1_v1.save()

    div2 = Division.create_initial(name="division2")

    c2 = Commit.objects.create(parent_commit=c)
    c2._add_versions([division1_v1, div2])
    c2 = get_refreshed(c2)
    self.assertEqual(
      c2.version_sets()[Division],
      { 
        division1_v1.eternal_id : division1_v1,
        div2.eternal_id : div2, 
      },
    )

    c3 = Commit.objects.create(parent_commit=c2)
    c3._remove_objects([division1_v1.eternal])
    c3 = get_refreshed(c3)
    self.assertEqual(
      c3.version_sets()[Division],
      { div2.eternal_id : div2 }
    )

