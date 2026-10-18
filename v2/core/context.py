from django.utils.translation import gettext_lazy as _

# (label, url name or admin path, permission needed) — grows as modules are added
MODULES = [
    (_("Cases"), "/backoffice/cases/beneficiary/", "cases.view_beneficiary"),
    (_("Aid"), "/backoffice/cases/aid/", "cases.view_aid"),
    (_("Donors"), "/backoffice/crm/donor/", "crm.view_donor"),
    (_("Donations"), "/backoffice/crm/donation/", "crm.view_donation"),
    (_("Campaigns"), "/backoffice/crm/campaign/", "crm.view_campaign"),
    (_("Sponsorships"), "/backoffice/crm/sponsorship/", "crm.view_sponsorship"),
    (_("Departments and projects"), "/backoffice/core/", "core.view_department"),
]


def navigation(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from approvals.services import inbox
    return {
        "nav_modules": [(label, url) for label, url, perm in MODULES if user.is_staff and user.has_perm(perm)],
        "approvals_waiting": len(inbox(user)),
    }
