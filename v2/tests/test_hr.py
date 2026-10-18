"""HR and payroll. Rates below are SAMPLE values for testing the arithmetic only;
real installs must enter the official rates, verified by a payroll specialist."""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from approvals import services
from core.models import Department, Project
from hr import payroll
from hr.models import (Assignment, Contract, Employee, EmployeePayItem, Grade, Incentive, InsuranceRule,
                       PayComponent, PayrollRun, Position, TaxBracket)

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def org(make_user):
    prog = Department.objects.create(code="PRG", name_ar="البرامج")
    admin_dept = Department.objects.create(code="ADM", name_ar="الإدارة")
    project = Project.objects.create(code="ORPH26", name_ar="كفالة الأيتام 2026", department=prog)
    grade = Grade.objects.create(code="G3", name_ar="الدرجة الثالثة", level=3, min_salary=D(6000), max_salary=D(15000))
    pos = Position.objects.create(code="SR", name_ar="باحث اجتماعي أول", department=prog, grade=grade, headcount=2)
    return {"prog": prog, "admin": admin_dept, "project": project, "grade": grade, "pos": pos,
            "hr_officer": make_user("hro", "hr_officer"), "hr_manager": make_user("hrm", "hr_manager"),
            "payroll": make_user("pay", "payroll_officer"), "executive": make_user("exe", "executive"),
            "researcher": make_user("res", "researcher")}


def hire(org, nid="29001011234567", salary=D(10000), hired=date(2026, 1, 1), **extra):
    emp = Employee.objects.create(name_ar="موظف", national_id=nid, department=org["prog"], position=org["pos"],
                                  grade=org["grade"], hire_date=hired, bank_name="بنك مصر",
                                  bank_account="EG00123", **extra)
    Contract.objects.create(employee=emp, contract_type="permanent", start_date=hired, basic_salary=salary)
    return emp


def sample_rules(year=2026):
    InsuranceRule.objects.create(year=year, employee_rate=D(11), employer_rate=D("18.75"), min_insurable=D(2000),
                                 max_insurable=D(12000), source="SAMPLE FOR TESTS", verified_by="test")
    for lower, upper, rate in ((0, 40000, 0), (40000, 55000, 10), (55000, 70000, 15), (70000, None, 20)):
        TaxBracket.objects.create(year=year, lower=D(lower), upper=D(upper) if upper else None, rate=D(rate),
                                  annual_exemption=D(20000) if lower == 0 else 0, source="SAMPLE FOR TESTS")


def test_employee_numbers_contract_and_assignment_rules(org):
    emp = hire(org)
    assert emp.employee_no == "E-2026-0001" and emp.contracts.get().contract_no.startswith("HR-2026-")
    with pytest.raises(ValidationError):        # outside grade range
        Contract(employee=emp, contract_type="permanent", start_date=date(2027, 1, 1), basic_salary=D(50000)).full_clean()
    with pytest.raises(ValidationError):        # overlaps the open-ended contract
        Contract(employee=emp, contract_type="permanent", start_date=date(2026, 6, 1), basic_salary=D(9000)).full_clean()
    with pytest.raises(ValidationError):        # fixed term needs an end date
        Contract(employee=emp, contract_type="fixed", start_date=date(2027, 1, 1), basic_salary=D(9000)).full_clean()
    Assignment.objects.create(employee=emp, department=org["prog"], project=org["project"], percent=D(60),
                              start_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):        # 60 + 50 > 100
        Assignment(employee=emp, department=org["admin"], percent=D(50), start_date=date(2026, 3, 1)).full_clean()
    with pytest.raises(ValidationError):        # project of another department
        Assignment(employee=emp, department=org["admin"], project=org["project"], percent=D(10),
                   start_date=date(2026, 3, 1)).full_clean()
    assert org["pos"].filled == 1


def test_payroll_refuses_without_configured_rules(org):
    hire(org)
    run = PayrollRun.objects.create(year=2026, month=3)
    with pytest.raises(payroll.PayrollError):
        payroll.calculate(run, org["payroll"])


def test_payroll_calculation_and_cost_allocation(org):
    sample_rules()
    emp = hire(org)
    transport = PayComponent.objects.create(code="TRN", name_ar="بدل انتقال", kind="earning", taxable=True, insurable=False)
    loan = PayComponent.objects.create(code="LOAN", name_ar="قسط سلفة", kind="deduction")
    EmployeePayItem.objects.create(employee=emp, component=transport, amount=D(500), start_date=date(2026, 1, 1))
    EmployeePayItem.objects.create(employee=emp, component=loan, amount=D(300), start_date=date(2026, 1, 1))
    Assignment.objects.create(employee=emp, department=org["prog"], project=org["project"], percent=D(60),
                              start_date=date(2026, 1, 1))
    run = payroll.calculate(PayrollRun.objects.create(year=2026, month=3), org["payroll"])
    s = run.payslips.get()
    assert s.basic == D("10000.00") and s.gross == D("10500.00")
    assert s.insurable_wage == D("10000.00") and s.insurance_employee == D("1100.00")
    assert s.insurance_employer == D("1875.00")
    # taxable 10500 - 1100 = 9400/month -> 112800/yr - 20000 = 92800
    # 40000@0 + 15000@10% + 15000@15% + 22800@20% = 0 + 1500 + 2250 + 4560 = 8310 /yr -> 692.50 /month
    assert s.income_tax == D("692.50")
    assert s.total_deductions == D("2092.50") and s.net == D("8407.50")
    assert s.employer_cost == D("12375.00")
    alloc = {(a["department"], a["project"]): D(a["amount"]) for a in s.allocation}
    assert alloc == {("PRG", "ORPH26"): D("7425.00"), ("PRG", ""): D("4950.00")}
    assert sum(alloc.values()) == s.employer_cost
    assert payroll.cost_by(run, "project") == {"ORPH26": D("7425.00"), "—": D("4950.00")}


def test_mid_month_joiner_is_prorated_and_cap_applies(org):
    sample_rules()
    hire(org, nid="29001011234568", salary=D(14000), hired=date(2026, 3, 17))
    s = payroll.calculate(PayrollRun.objects.create(year=2026, month=3), org["payroll"]).payslips.get()
    assert s.days_paid == 15 and s.basic == D("6774.19")              # 14000 × 15/31
    hire(org, nid="29001011234569", salary=D(15000), hired=date(2026, 1, 1))
    run = payroll.calculate(PayrollRun.objects.get(year=2026, month=3), org["payroll"])
    capped = run.payslips.get(basic=D("15000.00"))
    assert capped.insurable_wage == D("12000.00")                     # maximum insurable wage


def test_incentives_need_approval_before_payroll(org):
    sample_rules()
    emp = hire(org)
    inc = Incentive.objects.create(employee=emp, kind="bonus", amount=D(1000), pay_year=2026, pay_month=3,
                                   reason="مكافأة رمضان", requested_by=org["hr_officer"])
    run = PayrollRun.objects.create(year=2026, month=3)
    assert payroll.calculate(run, org["payroll"]).payslips.get().gross == D("10000.00")   # not yet approved
    req = services.submit(inc, org["hr_officer"])
    services.decide(req, org["hr_manager"], "approve")
    inc.refresh_from_db()
    assert inc.status == Incentive.APPROVED
    assert payroll.calculate(run, org["payroll"]).payslips.get().gross == D("11000.00")


def test_payroll_maker_checker_and_lock(org):
    sample_rules()
    emp = hire(org)
    emp.user = org["researcher"]
    emp.save()
    run = payroll.calculate(PayrollRun.objects.create(year=2026, month=3), org["payroll"])
    req = services.submit(run, org["payroll"])
    with pytest.raises(payroll.PayrollError):       # locked while awaiting approval
        payroll.calculate(run, org["payroll"])
    with pytest.raises(services.ApprovalError):
        services.decide(req, org["executive"], "approve")       # step 1 is the HR manager's
    services.decide(req, org["hr_manager"], "approve")
    services.decide(req, org["executive"], "approve")
    run.refresh_from_db()
    assert run.status == PayrollRun.APPROVED
    slip = run.payslips.get()
    c = Client()
    c.force_login(org["researcher"])                            # the employee sees their own payslip
    assert c.get(f"/hr/payslips/{slip.pk}/").status_code == 200
    c.force_login(org["hr_officer"])                            # HR officer: no salary access
    assert c.get(f"/hr/payslips/{slip.pk}/").status_code == 404


def test_payroll_preparer_cannot_approve_even_with_the_role(org, make_user):
    sample_rules()
    hire(org)
    both = make_user("both", "hr_manager", "payroll_officer")
    run = payroll.calculate(PayrollRun.objects.create(year=2026, month=4), both)
    req = services.submit(run, org["payroll"])                    # submitted by someone else
    assert not services.can_act(req, both)
    assert services.can_act(req, org["hr_manager"])


def test_salaries_hidden_from_hr_officer(org):
    emp = hire(org)
    c = Client()
    c.force_login(org["hr_officer"])
    page = c.get(f"/backoffice/hr/employee/{emp.pk}/change/").content.decode()
    assert "basic_salary" not in page and "bank_account" not in page and "national_id" in page
    assert c.get("/backoffice/hr/payrollrun/").status_code == 403
    assert not org["hr_officer"].has_perm("hr.view_salary")
    c.force_login(org["hr_manager"])
    page = c.get(f"/backoffice/hr/employee/{emp.pk}/change/").content.decode()
    assert "basic_salary" in page and "bank_account" in page
    assert not org["hr_manager"].has_perm("hr.run_payroll")


def test_structure_page_and_hr_dashboard(org):
    hire(org)
    c = Client()
    c.force_login(org["hr_officer"])
    html = c.get("/hr/structure/").content.decode()
    assert "باحث اجتماعي أول" in html and "موظف" in html
    dash = c.get("/").content.decode()
    assert "الموارد البشرية" in dash and "تكلفة الرواتب" not in dash      # no payroll money for the officer
    c.force_login(org["researcher"])
    assert c.get("/hr/structure/").status_code == 403
