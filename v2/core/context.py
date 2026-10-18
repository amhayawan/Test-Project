from django.utils.translation import gettext_lazy as _

# (label, url name or admin path, permission needed) — grows as modules are added
MODULES = [
    (_("Cases"), "/backoffice/cases/beneficiary/", "cases.view_beneficiary"),
    (_("Aid"), "/backoffice/cases/aid/", "cases.view_aid"),
    (_("Donors"), "/backoffice/crm/donor/", "crm.view_donor"),
    (_("Donations"), "/backoffice/crm/donation/", "crm.view_donation"),
    (_("Campaigns"), "/backoffice/crm/campaign/", "crm.view_campaign"),
    (_("Sponsorships"), "/backoffice/crm/sponsorship/", "crm.view_sponsorship"),
    (_("Employees"), "/backoffice/hr/employee/", "hr.view_employee"),
    (_("Organisation structure"), "/hr/structure/", "hr.view_position"),
    (_("Positions and job descriptions"), "/backoffice/hr/position/", "hr.view_position"),
    (_("Contracts"), "/backoffice/hr/contract/", "hr.view_contract"),
    (_("Incentives and penalties"), "/backoffice/hr/incentive/", "hr.view_incentive"),
    (_("Payroll"), "/backoffice/hr/payrollrun/", "hr.view_salary"),
    (_("Departments and projects"), "/backoffice/core/", "core.view_department"),
]


def navigation(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from approvals.services import inbox
    return {
        "nav_modules": [(label, url) for label, url, perm in MODULES
                        if user.has_perm(perm) and (user.is_staff or not url.startswith("/backoffice/"))],
        "has_employee_record": hasattr(user, "employee"),
        "approvals_waiting": len(inbox(user)),
    }
