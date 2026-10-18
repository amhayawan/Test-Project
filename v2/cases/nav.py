"""Menu entries for this module: (label, url, permission needed)."""
from django.utils.translation import gettext_lazy as _

GROUP = _("Case management")
ITEMS = [
    (_("Cases"), "/backoffice/cases/beneficiary/", "cases.view_beneficiary"),
    (_("Aid"), "/backoffice/cases/aid/", "cases.view_aid"),
]
