# Motivation

This project is a proof-of-concept for generic versioning of relational data with git-like capabilities. It arose from building a system that needed versioning, staging and retro-active changes of past data without modifying old versions. 

Right now, the project is split between "re-usable" components and an "example" app. At this point, it's hard to know what is truly re-usable so the example app contains a lot of exploratory logic. 

## Data model

### Versions

djangit is a "version-first" approach, a little bit like the pattern identified in this [blog post](http://strikingly.github.io/blog/2015/09/14/Simple-rails-history-pattern-ActiveRecord/). Many existing django versioning apps create mirroring "history" tables that synced via save() overrides or connecting signals (e.g. `post_save`) on your models. Instead, djangit makes you create history models directly and makes you use those models in your application. This means your primary keys are actually version-ids and your "object" keys are "eternal" ids.   


### Commits

Like git, djangit is also built around the idea of commits. A commit represents a a set of changes to a set of versioned data, along with some metadata.

Commits have a few properties:

* commits have a parent commit
  * if it's the 'initial' commit, then its parent is null
  * if it's a merge commit, then it has *multiple* parents - but this is not yet implemented
* commits store information that they change
  * in classic git, this can be thought of as a a set of (filename, line number, line content) pairs
  * in djangit, this is a set of versions that were added, replaced or removed
    * adding and replacing versions can both be represented as adding versions. We can check the commit's ancestors' added versions to look for the same eternal-id to figure out whether a commit is adding or replacing a version
    * removing a version is done with eternal ids
* commits may have additional metadata, such as an author, a timestamp and a message
* commits have a checksum attribute 
  * it is calculated from all of their fields: versions added/removed, parent commit and metadata (e.g. author, message, timestamp)
  * it is not calculated on any *external* factors, such as the current-time
  * it is not used as a unique-identifier, but as proof of validity 


### Foreign keys

Parent-child relationships between 2 versioned-models don't use version primary keys, but eternal IDs

### ManyToMany Pointer Models 

Since versioning is done at the row-level, and not the field-level, modifying a single field on a row will duplicate values of all the other fields in the database. If a field is expensive from a storage point of view, like a very big text field, you can create an intermediate 'pointer' model that contains the value of the field, and keep a foreign key to that pointer model. When you want to modify a version, you first check whether the new value matches the existing pointer entry. If not, you create a new pointer row with the new field value 

Pointer models are not currently used for 'scalar' fields, but they are used for many-to-many fields. The many-to-many relation essentially gets moved from the version-model to a intermediate pointer model. 

One alternative we considered here was using comma-separated eternal primary-keys and storing those in a text-field, but that has the disadvantage of losing database-backed relational integrity. 


### Working directory/Staging area ? 

Classic git has 3 areas. The working directory, the staging area and your committed versions. 

In djangit, the commit object occupies all of these roles. Versions that are being "worked on" have to be referenced from somewhere, so we use a commit object to hold on to these foreign keys. The difference between a commit that is "worked on" and a commit that is "finalized" is the presence of the checksum attribute. The workflow for modifying a version and commiting it is as follows:

1. "checkout" a commit
    * this could have side effects (e.g. setting a value in a `UserCheckedOutCommit` table) or could just be based on a URL param
    * your specific user-interface should show a list of objects that can be viewed and modified
2. modify a version via a form submission
    1. the form will create a new version of an object
    2. it will create a new commit (whose parent is the previously checked-out commit)
    3. and will link the new version and commit to each other
    4. it will (conceptually) modify the "checked_out" commit to the newly created commit
      * as mentioned above, this could have side-effects or it could just be a redirect with a new URL param
3. Use a staging form to finalize changes
    * some kind of diff-view with a collection of checkboxes to decide what to include
    * submitting this form would
      1. create a new 'staged' commit (w/ parent=checked out)
      2. add the 'staged' versions to the new commit
      3. remove those same versions from the 'working' commit
      4. finalize the staged commit
      5. change the "checked_out" commit's parent to the newly finalized commit



## Unsolved challenges

### Constraints

Django makes it easy to implement database-backed constraints such as "the `BookRevenue`'s year and book_id should be unique together" Unfortunately, with versions, we want to allow the possibility of having multiple versions of a `BookRevenue`, which would break this constraint. Many types of constraints may have to be checked at commit-finalization time instead of on a row-level transaction basis. 

### Many to many relations where we care about both sides

djangit offers tracking of many-to-many relations, but it only tracks the changes from one side of the relation (the side that defines the field). In other words, if a Book model has a many-to-many field to a `CategoryTag`, it's easy to find which tags a particular book version had, but it's difficult to find out what books were related to a specific version of a category tag. This kind of question can be answered if versions and commits are all time-stamped, though. 


### Migrations and decentralization

(This feature is not an especially important priority)

Like git, djangit is also ideally de-centralizable. One potential benefit to this is that it would allow temporarily classified information (e.g. a proposed 'branch' of commits that are considered top-secret until publically announced) to be created in a different database with higher classification ratings.

All this is possible because checksums can be checked from the data, and checksums will allow you to validate that two databases are properly sync-able.

The problem is, if someone modifies the data model of a versioned model, the default checksum function may no longer produce the existing checksums. 

One workaround I *think* might work would be do recompute all checksums on any migration. If checksums are using the right attributes, objects from two independent databases with matching pre-migration checksums should also have matching post-migration checksums. Checksum functions need to remain pure-functions that don't use outside information like the current time.  

### Truly deleting information

At some point, someone is going to input classified information in a system they shouldn't have. If they notice after finalizing commits, removing the bad information is non-trivial, all downstream commits will have to have their checksums recomputed.


# Where things are right now/ TODO: 

* Views! 
  * we need a ModelForm-like FormClass that will:
    * display ManyToManyPointer fields with normal many-to-many widgets
    * will perform "copy on write" logic when saved()


* We don't yet support merge commits. This means we'll need to turn the parent commit foreign key into a many-to-many relation
  * once merge commits are working, we can figure out how to do conflict resolution
    * conflict detection: By default, conflicts should only occur when two commits' mutually-exclusive chains contain changes to the same 'eternal-record' and the **field**
      * presumably, we could have "conflict resolution" hooks to have custom rules. For instance, two really closely related fields that are expected to change together but change independently could present a conflict.
    * for a merge between 2 versions, we can present 3 forms, two readonly forms showing the contents of the 2 original versions, and another to fill in the "resolved merge"





## A note on performance

* Since it is common to do queries of the form "get all the ancestors of this commit", and that commits identify their parent via a relation, you can end up with an indefinite amount of self-joins. That's a hell of an N+1 problem! To get around this, we should look into replacing the parent-commit foreign key with specialized structures such as [django-mptt](https://django-mptt.readthedocs.io/en/latest/index.html) or [django-treebeard](https://django-treebeard.readthedocs.io/en/latest/). A many-to-many tree lookup will also be necessary once we allow merge commits.


## Weird things explained

### Eternal IDs

for ORM interop purposes, Eternal IDs are backed by their own model/table instead of just being a simple column
* Although eternal IDs have a single purpose, it wasn't super straightforward to create a cross-database solution that supports
    1. race-condition-safe, auto-incrementing unique sequences
    2. having django store a foreign key to something that isn't the primary key of another model
* At some point, we may end up storing other fields on the eternal model, there's little harm in keeping them around

