from examples.models import Commit, Division, Tag


def create_data():
  c0 = Commit.objects.create()

  division_v0 = Division.create_initial(
    name="division1",
  )
  division_v1 = division_v0.clone()

  c0._add_versions([division_v0])
  c0.commit()


  division_v1.name="division one"
  division_v1.save()

  
  t1 =  Tag.create_initial(name="category 1")
  t2 = Tag.create_initial(name="category 2")
  division2_v0 = Division.create_initial(
    name="division 2",
  )
  division3_v0 = Division.create_initial(
    name="division 3",
  )
  division3_v0.set_m2m('tags', [t1.eternal_id,t2.eternal_id])

  c1 = Commit.objects.create(parent_commit=c0)
  c1._add_versions([ division_v1 ])
  c1.commit()

  c2 = Commit.objects.create(parent_commit=c1)
  c2._add_versions([division2_v0, division3_v0])
  c2._remove_objects([division_v0.eternal])
  c2.commit()

