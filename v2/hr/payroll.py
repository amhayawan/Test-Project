"""Monthly payroll calculation.

For each employee with a contract in the month:
  basic          = contract basic salary, pro-rated by calendar days employed in the month
  earnings       = recurring allowances (fixed or % of basic) + APPROVED incentives/bonuses/overtime
  insurable wage = basic + insurable allowances, kept between the year's minimum and maximum
  insurance      = insurable wage × employee rate (deducted) / × employer rate (association cost)
  income tax     = (taxable gross − employee insurance) × 12 → annual brackets − exemption → ÷ 12
  deductions     = insurance + tax + recurring deductions + approved penalties
  net            = gross − deductions
  employer cost  = gross + employer insurance, split across assignments (rest → home department)

The run refuses to calculate until that year's insurance rule and tax brackets exist.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import log_event

from .models import (Employee, EmployeePayItem, Incentive, InsuranceRule, Payslip, PayrollRun, PayComponent,
                     TaxBracket, annual_tax, money, month_bounds, overlaps)


class PayrollError(Exception):
    pass


def _employed_days(emp, contract, start, end):
    first = max(start, emp.hire_date, contract.start_date)
    last = min([end] + [d for d in (emp.end_date, contract.end_date) if d])
    return max((last - first).days + 1, 0)


def _allocation(emp, cost, start, end):
    parts = [a for a in emp.assignments.select_related("department", "project")
             if overlaps(a.start_date, a.end_date, start, end)]
    lines, used = [], Decimal(0)
    for a in parts:
        amount = money(cost * a.percent / 100)
        used += amount
        lines.append({"department": a.department.code, "project": a.project.code if a.project else "",
                      "percent": str(a.percent), "amount": str(amount)})
    rest = cost - used
    if rest > 0:
        share = Decimal(100) - sum((a.percent for a in parts), Decimal(0))
        lines.append({"department": emp.department.code, "project": "", "percent": str(share),
                      "amount": str(money(rest))})
    return lines


def payslip_for(run, emp, rule):
    start, end = month_bounds(run.year, run.month)
    contract = emp.contract_on(end) or emp.contract_on(start)
    if not contract:
        return None
    days = _employed_days(emp, contract, start, end)
    if days == 0:
        return None
    month_days = (end - start).days + 1
    basic = money(contract.basic_salary * days / month_days)
    lines = []
    taxable, insurable_extra, extra_deductions, earnings = basic, Decimal(0), Decimal(0), Decimal(0)
    items = EmployeePayItem.objects.filter(employee=emp, start_date__lte=end).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=start)).select_related("component")
    for item in items:
        value = item.value_for(basic)
        comp = item.component
        lines.append({"code": comp.code, "name": comp.name_ar, "kind": comp.kind, "amount": str(value)})
        if comp.kind == PayComponent.EARNING:
            earnings += value
            taxable += value if comp.taxable else 0
            insurable_extra += value if comp.insurable else 0
        else:
            extra_deductions += value
    for inc in Incentive.objects.filter(employee=emp, pay_year=run.year, pay_month=run.month,
                                        status=Incentive.APPROVED):
        value = money(inc.amount)
        if inc.kind == "penalty":
            lines.append({"code": "PENALTY", "name": inc.reason, "kind": "deduction", "amount": str(value)})
            extra_deductions += value
        else:
            lines.append({"code": inc.kind.upper(), "name": inc.reason, "kind": "earning", "amount": str(value)})
            earnings += value
            taxable += value
    gross = basic + earnings
    insurable = min(max(basic + insurable_extra, rule.min_insurable), rule.max_insurable)
    ins_emp = money(insurable * rule.employee_rate / 100)
    ins_er = money(insurable * rule.employer_rate / 100)
    monthly_taxable = max(taxable - ins_emp, Decimal(0))
    tax = money(annual_tax(run.year, monthly_taxable * 12) / 12)
    deductions = ins_emp + tax + extra_deductions
    cost = gross + ins_er
    return Payslip(run=run, employee=emp, days_paid=days, basic=basic, lines=lines, gross=money(gross),
                   insurable_wage=money(insurable), insurance_employee=ins_emp, insurance_employer=ins_er,
                   income_tax=tax, total_deductions=money(deductions), net=money(gross - deductions),
                   employer_cost=money(cost), allocation=_allocation(emp, money(cost), start, end),
                   bank_name=emp.bank_name, bank_account=emp.bank_account)


@transaction.atomic
def calculate(run, user):
    run = PayrollRun.objects.select_for_update().get(pk=run.pk)
    if run.locked:
        raise PayrollError(_("This payroll is awaiting approval or already approved and cannot be recalculated."))
    rule = InsuranceRule.objects.filter(year=run.year).first()
    if not rule or not TaxBracket.objects.filter(year=run.year).exists():
        raise PayrollError(_("Payroll rules for %(year)s are not configured: enter the social insurance rule and "
                             "income tax brackets (verified by a payroll specialist) first.") % {"year": run.year})
    start, end = month_bounds(run.year, run.month)
    run.payslips.all().delete()
    slips = []
    candidates = Employee.objects.filter(hire_date__lte=end).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=start)).select_related("department")
    for emp in candidates:
        slip = payslip_for(run, emp, rule)
        if slip:
            slips.append(slip)
    Payslip.objects.bulk_create(slips)
    run.total_gross = sum((s.gross for s in slips), Decimal(0))
    run.total_net = sum((s.net for s in slips), Decimal(0))
    run.total_cost = sum((s.employer_cost for s in slips), Decimal(0))
    run.prepared_by = user
    run.calculated_at = timezone.now()
    run.status = PayrollRun.DRAFT
    run.save()
    log_event("payroll_calculated", run, summary=f"{len(slips)} payslips, net {run.total_net}")
    return run


def cost_by(run, key):
    """Total employer cost per department or project code, from the payslip allocations."""
    totals = {}
    for slip in run.payslips.all():
        for line in slip.allocation:
            k = line[key] or "—"
            totals[k] = totals.get(k, Decimal(0)) + Decimal(line["amount"])
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))
