from unittest import skip

from django.test import TestCase


from .create_data import create_data
from examples.models import Division, Team, Tag, Employee, Commit
from djangit.utils import LockedInformationException




class BasicTestCase(TestCase):

  # @classmethod
  # def setUpTestData(cls):
  #   create_data()


  @skip("old")
  def test_stuff(self):

    div = Division.create_initial(name="division")
    tm1 = Team.create_initial(name="team1", division=div)
    tm2 = Team.create_initial(name="team2", division=div)
    e1 = Employee.create_initial(name="emp1",team=tm1)
    e2 = Employee.create_initial(name="emp2",team=tm1)
    e3 = Employee.create_initial(name="emp3",team=tm2)

    tg1 = Tag.create_initial(name="gets stuff done")
    tg2 = Tag.create_initial(name="new")

    tm1.tags.add(tg1)
    e3.tags.add(tg2)

    # create initial versions
    for obj in (div, tm1, tm2, e1, e2, e3, tg1, tg2 ):
      create_initial_version(obj)
      self.assertEqual(obj.versions.count(), 1)

    tm1_v0 = tm1.versions.first()
    tm1.name = "new team 1 name"
    tm1.save()
    tm1.tags.add(tg2)
    tm1.tags.remove(tg1)

    tm1_v1 = save_instance_and_create_version(tm1, tm1_v0)

    self.assertNotEqual(tm1_v1, tm1_v0)
    self.assertNotEqual(tm1_v1.name, tm1_v0.name)
    self.assertNotEqual(tm1_v1.tags, tm1_v0.tags)
    self.assertEqual(tm1_v0.division, tm1_v1.division)


    tm1.name = "even newer team 1 name"
    tm1.save()
    tm1_v2 = save_instance_and_create_version(tm1, tm1_v1)
    self.assertNotEqual(tm1_v2, tm1_v1)
    self.assertNotEqual(tm1_v2.name, tm1_v1.name)
    self.assertEqual(tm1_v2.tags, tm1_v1.tags)
    self.assertEqual(tm1_v2.division, tm1_v1.division)

    

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


    
    t1 =  Tag.create_initial(name="category 1")
    t2 = Tag.create_initial(name="category 2")
    division2_v0 = Division.create_initial(
      name="division 2",
    )
    division3_v0 = Division.create_initial(
      name="division 3",
    )
    division3_v0.set_m2m('tags', [t1.eternal_id,t2.eternal_id])

    division3_v0.refresh_from_db()
    self.assertTrue(division3_v0.tags)
    self.assertEqual(
      set(division3_v0.tags.related.all()),
      set([t1.eternal,t2.eternal])
    )

    c1 = Commit.objects.create(parent_commit=c0)
    c1._add_versions([ division_v1 ])
    c1._add_versions([ t1, t2 ])
    c1.commit()

    with self.assertRaises(LockedInformationException):
      c1.save()
    
    with self.assertRaises(LockedInformationException):
      division_v1.refresh_from_db()
      division_v1.save()
    
    
    with self.assertRaises(LockedInformationException):
      t1.refresh_from_db()
      t1.save()

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
