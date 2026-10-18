"""Role catalogue. Each role is a Django group holding model permissions.

Patterns use shell wildcards ("hr.*", "crm.view_*"); a pattern starting with "-" removes
permissions matched earlier (e.g. "-hr.run_payroll").

Permissions are standard Django ones ("app.view_model", "app.add_model", ...) plus a few
custom ones declared in each app's Meta.permissions (e.g. "cases.approve_case").
Run `python manage.py setup_roles` after migrations; it is safe to run again.
"""
from django.utils.translation import gettext_lazy as _

ROLES = {
    "admin": (_("System administrator"), ["*"]),
    "executive": (_("Executive director"), [
        "core.view_*", "crm.view_*", "cases.view_*", "cases.view_all_cases", "cases.view_case_funding",
        "approvals.view_*", "accounts.view_user",
        "hr.view_employee", "hr.view_position", "hr.view_payrollrun", "hr.view_payslip", "hr.view_salary",
    ]),
    "case_manager": (_("Case manager"), [
        "core.view_department", "core.view_project", "core.view_fund", "core.view_attachment", "core.add_attachment",
        "cases.*", "cases.view_all_cases", "cases.assign_case", "cases.approve_case", "cases.view_case_funding",
        "crm.view_donor", "crm.view_donation", "crm.view_campaign", "crm.*_sponsorship",
        "approvals.view_approvalrequest",
    ]),
    "researcher": (_("Field researcher"), [
        "core.view_attachment", "core.add_attachment",
        "cases.view_beneficiary", "cases.add_beneficiary", "cases.change_beneficiary",
        "cases.*_familymember", "cases.view_caseneed", "cases.add_caseneed",
        "cases.recommend_case",
    ]),
    "fundraising": (_("Fundraising / donations officer"), [
        "core.view_department", "core.view_project", "core.view_fund", "core.view_attachment", "core.add_attachment",
        "crm.*", "cases.view_beneficiary", "cases.view_all_cases", "cases.view_caseneed", "cases.view_case_funding",
        "cases.add_beneficiary",
    ]),
    "hr_manager": (_("HR manager"), [
        "core.view_department", "core.view_project", "core.view_attachment", "core.add_attachment",
        "core.change_attachment", "hr.*", "-hr.run_payroll", "accounts.view_user",
    ]),
    "hr_officer": (_("HR officer"), [
        "core.view_department", "core.view_project", "core.view_attachment", "core.add_attachment",
        "hr.view_employee", "hr.view_contract", "hr.view_grade", "hr.view_paycomponent", "hr.view_incentive",
        "hr.add_employee", "hr.change_employee", "hr.add_contract", "hr.change_contract",
        "hr.*_assignment", "hr.*_appraisal", "hr.*_position", "hr.add_incentive", "hr.change_incentive",
    ]),
    "payroll_officer": (_("Payroll officer"), [
        "core.view_department", "core.view_project", "hr.view_*", "hr.view_salary", "hr.run_payroll",
        "hr.*_payrollrun", "hr.*_employeepayitem", "hr.add_incentive", "hr.change_incentive",
        "hr.*_paycomponent",
    ]),
}

EXECUTIVE_APPROVER = "executive"


def role_label(code):
    entry = ROLES.get(code)
    return entry[0] if entry else code
