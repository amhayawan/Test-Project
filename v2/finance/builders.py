"""How each business event is booked. Accounts come from the posting rules (AccountMapping)."""
from decimal import Decimal

from django.utils.translation import gettext as _

from core.models import Department, Fund, Project

from .models import ZERO, mapped, money

ZAKAT_PURPOSES = ("zakat", "zakat_fitr")


def default_fund(zakat=False):
    kind = Fund.ZAKAT if zakat else Fund.UNRESTRICTED
    return Fund.objects.filter(kind=kind, is_active=True).order_by("code").first()


# ---------------------------------------------------------------- donations

def donation(d, **_extra):
    """Dr cash / bank / wallet — Cr donation income (by purpose), in the donation's fund and campaign project."""
    if d.method == "in_kind":
        return None           # goods are booked by the storekeeper's goods receipt at their value
    fund = d.fund or default_fund(d.purpose in ZAKAT_PURPOSES)
    project = d.campaign.project if d.campaign_id and d.campaign.project_id else None
    memo = f"{d.receipt_no} {d.donor}"
    return {"date": d.donation_date, "source": "donation",
            "description": _("Donation %(no)s — %(donor)s") % {"no": d.receipt_no, "donor": d.donor},
            "lines": [
                {"account": mapped(f"cash.{d.method}", "cash.cash"), "debit": d.amount, "fund": fund, "memo": memo},
                {"account": mapped(f"income.{d.purpose}", "income.general"), "credit": d.amount, "fund": fund,
                 "project": project, "memo": memo},
            ]}


# ---------------------------------------------------------------- aid to cases

def aid(a, **_extra):
    """Dr aid expense (by aid type) — Cr cash / bank. Goods from the store are booked by the stock issue."""
    if a.status != a.DELIVERED or a.paid_by == "stock":
        return None
    fund = a.fund or default_fund()
    memo = f"{a.aid_no} {a.beneficiary.case_no}"
    return {"date": a.delivered_on, "source": "aid",
            "description": _("Aid %(no)s — case %(case)s") % {"no": a.aid_no, "case": a.beneficiary.case_no},
            "lines": [
                {"account": mapped(f"aid.expense.{a.aid_type}", "aid.expense"), "debit": a.value, "fund": fund,
                 "project": a.project, "memo": memo},
                {"account": mapped(f"cash.{a.paid_by}", "cash.cash"), "credit": a.value, "fund": fund, "memo": memo},
            ]}


# ---------------------------------------------------------------- payroll

def _split(amount, shares):
    """Split an amount by shares (that sum to 1); rounding difference goes to the largest part."""
    parts = [money(amount * s) for s in shares]
    if parts:
        parts[max(range(len(parts)), key=lambda i: parts[i])] += money(amount) - sum(parts)
    return parts


def payroll_approved(run, **_extra):
    """Accrue the month: Dr salaries and employer insurance by cost centre / project —
    Cr net pay payable, income tax payable, social insurance payable, staff loans, penalties."""
    from hr.models import month_bounds
    _start, end = month_bounds(run.year, run.month)
    depts = {d.code: d for d in Department.objects.all()}
    projects = {p.code: p for p in Project.objects.select_related("fund")}
    general = default_fund()
    salary_acc, insurance_acc = mapped("payroll.salaries"), mapped("payroll.employer_insurance")
    cost = {}                                   # (department, project) → [salaries, employer insurance]
    net = tax = insurance = loans = penalties = ZERO
    for slip in run.payslips.all():
        unpaid = sum((Decimal(l["amount"]) for l in slip.lines if l.get("reduces_pay")), ZERO)
        slip_penalties = sum((Decimal(l["amount"]) for l in slip.lines if l.get("code") == "PENALTY"), ZERO)
        other = slip.total_deductions - slip.insurance_employee - slip.income_tax - unpaid - slip_penalties
        salaries = slip.gross - unpaid
        total = slip.employer_cost or Decimal(1)
        shares = [Decimal(a["amount"]) / total for a in slip.allocation]
        for a, s_part, i_part in zip(slip.allocation, _split(salaries, shares), _split(slip.insurance_employer, shares)):
            key = (a["department"], a["project"])
            row = cost.setdefault(key, [ZERO, ZERO])
            row[0] += s_part
            row[1] += i_part
        net += slip.net
        tax += slip.income_tax
        insurance += slip.insurance_employee + slip.insurance_employer
        loans += other
        penalties += slip_penalties
    lines = []
    for (dept_code, project_code), (salaries, ins) in sorted(cost.items()):
        project = projects.get(project_code) if project_code else None
        fund = project.fund if project and project.fund_id else general
        for account, amount in ((salary_acc, salaries), (insurance_acc, ins)):
            lines.append({"account": account, "debit": amount, "fund": fund, "project": project,
                          "department": depts.get(dept_code)})
    for key, amount in (("payroll.net_payable", net), ("payroll.tax_payable", tax),
                        ("payroll.insurance_payable", insurance), ("payroll.deductions", loans),
                        ("payroll.penalties", penalties)):
        if amount:
            lines.append({"account": mapped(key), "credit": amount, "fund": general})
    return {"date": end, "source": "payroll", "lines": lines,
            "description": _("Payroll %(month)s") % {"month": run}}


def payroll_paid(run, day=None, **_extra):
    """Salaries transferred: Dr net pay payable — Cr bank."""
    general = default_fund()
    return {"date": day or run.calculated_at.date(), "source": "payroll",
            "description": _("Salaries paid %(month)s") % {"month": run},
            "lines": [{"account": mapped("payroll.net_payable"), "debit": run.total_net, "fund": general},
                      {"account": mapped("cash.bank"), "credit": run.total_net, "fund": general}]}


# ---------------------------------------------------------------- payments

def payment(p, **_extra):
    """Dr what was paid (supplier, expense, advance) — Cr cash / bank."""
    fund = p.fund or default_fund()
    return {"date": p.date, "source": "payment",
            "description": _("Payment %(no)s — %(payee)s") % {"no": p.payment_no, "payee": p.payee},
            "lines": [{"account": p.debit_account, "debit": p.amount, "fund": fund, "project": p.project,
                       "department": p.department, "memo": p.description},
                      {"account": mapped(f"cash.{p.method}", "cash.bank"), "credit": p.amount, "fund": fund,
                       "memo": p.description}]}
