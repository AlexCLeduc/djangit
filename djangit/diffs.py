import difflib

from django.utils.html import escape

class Diff:

  @staticmethod
  def replace_diff_tags_with_html(s):
    return (
      s.replace('\00+','<span class="diff_add">')
      .replace('\00-','<span class="diff_sub">')
      .replace('\00^','<span class="diff_chg">')
      .replace('\01','</span>')
    )

  def __init__(self,field,version,original,vlast,last_original):
    self.field = field
    self.version = version
    self.original= original
    self.versionlast = vlast
    self.last_original = last_original
    self.original_class_name = self.original.__class__.__name__
    if self.field:
      self.id = f"{self.original_class_name}-{version.id}-{field.name}"
    else:
      self.id = f"{self.original_class_name}-{version.id}-creation"

  def diff(self):
    if not self.field:
      return False


    if self.field.choices:
      # if a field is a choice field e.g. chars or ints used to represent a list of choices,
      # then its value is just that database, non-bilingual char/int value
      # fortunately model instances provide a hook for this
      func_name = f"get_{self.field.name}_display"
      last_original = getattr(self.last_original, func_name)()
      original = getattr(self.original, func_name)()
    else:
      last_original = getattr(self.last_original,self.field.name)
      original = getattr(self.original,self.field.name)


    if last_original is None:
      last_original = "empty"
    if original is None:
      original = "empty"
    # if isinstance(self.field,fields.MarkdownField):
    #   return (
    #     escape(last_original),
    #     escape(original)
    #   )
    mdiff = next(difflib._mdiff(
      [escape(last_original)],
      [escape(original)]
    ))
    return (
      Diff.replace_diff_tags_with_html(mdiff[0][1]),
      Diff.replace_diff_tags_with_html(mdiff[1][1]),
    )

  def is_annotated(self):
    return not (
      self.version.cosmetic_change is False and
      (
        not self.version.reason_for_substantive_change_en or
        not self.version.reason_for_substantive_change_fr
      ) and
      self.field is not None
    )

  def name(self):
    if hasattr(self.original, "name"):
      return self.original.name
    else:
      return "N/A"

  def model(self):
    return self.original._meta.verbose_name

  def action(self):
    if not self.field:
      return "created"
    elif hasattr(self.original, "last_active_year") and self.original.last_active_year:
      return "deactivated"
    else:
      return "edited"

  def __repr__(self):
    if not self.field:
      return "<Diff - New Record>"
    return f"<Diff - {self.field.name}>"

class TagM2MDiff(Diff):
  def __init__(self,*args, **kwargs):
    super().__init__(*args, **kwargs)
    self.id = self.id
    self.related_model = self.field.related_model


  def action(self):
    return "tagging changes"

  def diff(self):
    get_name = lambda tag: tag.name
    current_tags = sorted(self.version.get_m2m(self.field), key=get_name)
    old_tags = sorted(self.versionlast.get_m2m(self.field), key=get_name)

    rm_cls = "diff_sub"
    add_cls = "diff_add"
    empty_str = ""

    left = [
      f"<p class='{rm_cls if tag not in current_tags else empty_str}'>{tag.name}</p>"
      for tag in old_tags
    ]

    right = [
      f"<p class={add_cls if tag not in old_tags else empty_str}>{tag.name}</p>"
      for tag in current_tags
    ]



    return (
      "".join(left),
      "".join(right),
    )