"""Menu entries for this module: (label, url, permission needed)."""
from django.utils.translation import gettext_lazy as _

GROUP = _("Human resources")
ITEMS = [
    (_("Employees"), "/backoffice/hr/employee/", "hr.view_employee"),
    (_("Organisation structure"), "/hr/structure/", "hr.view_position"),
    (_("Positions and job descriptions"), "/backoffice/hr/position/", "hr.view_position"),
    (_("Contracts"), "/backoffice/hr/contract/", "hr.view_contract"),
    (_("Incentives and penalties"), "/backoffice/hr/incentive/", "hr.view_incentive"),
    (_("Leave requests"), "/backoffice/hr/leaverequest/", "hr.view_leaverequest"),
    (_("Leave types and rules"), "/backoffice/hr/leavetype/", "hr.view_leavetype"),
    (_("Official holidays"), "/backoffice/hr/publicholiday/", "hr.view_publicholiday"),
    (_("Payroll"), "/backoffice/hr/payrollrun/", "hr.view_salary"),
]
