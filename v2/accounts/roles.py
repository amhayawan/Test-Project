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
        "finance.view_*", "supply.view_*", "projects.view_*", "projects.view_all_projects",
    ]),
    "case_manager": (_("Case manager"), [
        "core.view_department", "core.view_project", "core.view_fund", "core.view_attachment", "core.add_attachment",
        "cases.*", "cases.view_all_cases", "cases.assign_case", "cases.approve_case", "cases.view_case_funding",
        "crm.view_donor", "crm.view_donation", "crm.view_campaign", "crm.*_sponsorship",
        "approvals.view_approvalrequest", "supply.view_purchaserequest", "supply.add_purchaserequest",
        "supply.change_purchaserequest", "supply.*_purchaserequestline", "supply.view_item",
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
        "core.change_attachment", "hr.*", "-hr.run_payroll", "-hr.verify_hr_rules", "accounts.view_user",
    ]),
    "hr_officer": (_("HR officer"), [
        "core.view_department", "core.view_project", "core.view_attachment", "core.add_attachment",
        "hr.view_employee", "hr.view_contract", "hr.view_grade", "hr.view_paycomponent", "hr.view_incentive",
        "hr.add_employee", "hr.change_employee", "hr.add_contract", "hr.change_contract",
        "hr.*_assignment", "hr.*_appraisal", "hr.*_position", "hr.add_incentive", "hr.change_incentive",
        "hr.view_leavetype", "hr.view_leaveentitlement", "hr.view_publicholiday", "hr.*_leaverequest",
        "hr.view_leaveadjustment", "hr.add_leaveadjustment",
    ]),
    "labour_specialist": (_("Labour-law / payroll specialist (signs off rules)"), [
        "hr.view_leavetype", "hr.view_leaveentitlement", "hr.view_publicholiday", "hr.view_insurancerule",
        "hr.view_taxbracket", "hr.verify_hr_rules",
    ]),
    "finance_manager": (_("Finance manager"), [
        "core.view_*", "core.add_attachment", "finance.*", "crm.view_donation", "crm.view_donor", "crm.view_campaign",
        "cases.view_aid", "hr.view_payrollrun", "supply.view_*", "projects.view_*", "projects.view_all_projects",
        "approvals.view_approvalrequest",
    ]),
    "accountant": (_("Accountant"), [
        "core.view_department", "core.view_project", "core.view_fund", "core.view_attachment", "core.add_attachment",
        "finance.view_*", "finance.add_journalentry", "finance.change_journalentry", "finance.*_journalline",
        "finance.add_payment", "finance.change_payment", "finance.*_fixedasset", "finance.add_depreciationrun",
        "finance.change_depreciationrun", "supply.view_*", "supply.*_supplierinvoice", "supply.*_supplierinvoiceline",
        "crm.view_donation", "projects.view_*", "projects.view_all_projects",
    ]),
    "procurement_officer": (_("Procurement officer"), [
        "core.view_department", "core.view_project", "core.view_fund", "core.view_attachment", "core.add_attachment",
        "supply.view_*", "supply.*_supplier", "supply.*_item", "supply.*_itemcategory",
        "supply.*_purchaserequest", "supply.*_purchaserequestline", "supply.*_purchaseorder", "supply.*_purchaseorderline",
    ]),
    "storekeeper": (_("Storekeeper"), [
        "core.view_department", "core.view_project", "core.view_attachment", "core.add_attachment",
        "supply.view_item", "supply.view_itemcategory", "supply.view_warehouse", "supply.view_purchaseorder",
        "supply.view_purchaseorderline", "supply.view_stockmove", "supply.*_goodsreceipt", "supply.*_goodsreceiptline",
        "supply.*_stockissue", "supply.*_stockissueline", "cases.view_aid", "crm.view_donation",
    ]),
    "project_manager": (_("Project manager"), [
        "core.view_department", "core.view_project", "core.view_fund", "core.view_attachment", "core.add_attachment",
        "projects.*", "-projects.view_all_projects", "supply.view_purchaserequest", "supply.add_purchaserequest",
        "supply.change_purchaserequest", "supply.*_purchaserequestline", "supply.view_item",
    ]),
    # Not a group people are put in: an approval step for this role goes to the employee's own manager.
    "line_manager": (_("Line manager (of the employee)"), []),
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
