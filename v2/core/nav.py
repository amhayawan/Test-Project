"""Menu entries for this module: (label, url, permission needed)."""
from django.utils.translation import gettext_lazy as _

GROUP = _("Organisation")
ITEMS = [
    (_("Departments and projects"), "/backoffice/core/", "core.view_department"),
]
