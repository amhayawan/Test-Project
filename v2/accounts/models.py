from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """One login per person. Roles are Django groups (see accounts/roles.py)."""

    name_ar = models.CharField(_("name (Arabic)"), max_length=160, blank=True)
    name_en = models.CharField(_("name (English)"), max_length=160, blank=True)
    language = models.CharField(_("language"), max_length=5, choices=settings.LANGUAGES, default="ar")
    department = models.ForeignKey("core.Department", verbose_name=_("department"), null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="staff")
    # Data scope: which departments / projects this user may see in scoped lists (empty = own only).
    scope_departments = models.ManyToManyField("core.Department", verbose_name=_("department scope"),
                                               blank=True, related_name="+")
    scope_projects = models.ManyToManyField("core.Project", verbose_name=_("project scope"), blank=True,
                                            related_name="+")
    failed_logins = models.PositiveSmallIntegerField(default=0, editable=False)
    locked_until = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        from django.utils.translation import get_language
        preferred = self.name_en if (get_language() or "ar").startswith("en") else self.name_ar
        return preferred or self.name_ar or self.name_en or self.get_full_name() or self.username

    def has_role(self, *codes):
        return self.is_superuser or self.groups.filter(name__in=codes).exists()

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    @property
    def role_names(self):
        from .roles import role_label
        return [role_label(g.name) for g in self.groups.all()]
