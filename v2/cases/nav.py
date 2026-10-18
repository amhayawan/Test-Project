"""Menu entries for this module: (label, url, permission needed)."""
from django.utils.translation import gettext_lazy as _

GROUP = _("Case management")
ITEMS = [
    (_("Cases"), "/backoffice/cases/beneficiary/", "cases.view_beneficiary"),
    (_("Referred to the Projects Department"),
     "/backoffice/cases/beneficiary/?status__exact=approved&referred_at__isempty=0", "cases.add_aid"),
    (_("Aid"), "/backoffice/cases/aid/", "cases.view_aid"),
    (_("Cases available for donors (by code)"), "/cases/available/", "cases.view_case_summary"),
    (_("Blank research form (print)"), "/cases/research-form/blank/", "cases.add_beneficiary"),
]
