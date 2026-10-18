"""Finance section of the dashboard (finance roles and management)."""
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from dashboards.widgets import bar_rows

from . import reports
from .models import ZERO, Account, FinanceError, JournalEntry, Payment, PostingIssue, mapped


def finance(user, f):
    if not user.has_perm("finance.view_journalline"):
        return None
    dims = {"fund": f.fund, "project": f.project, "department": f.department}
    period = reports.posted(f.start, f.end, **dims)
    income = period.filter(account__kind=Account.INCOME).aggregate(d=Sum("debit"), c=Sum("credit"))
    expense = period.filter(account__kind=Account.EXPENSE).aggregate(d=Sum("debit"), c=Sum("credit"))
    income_v = (income["c"] or ZERO) - (income["d"] or ZERO)
    expense_v = (expense["d"] or ZERO) - (expense["c"] or ZERO)
    try:
        cash_accounts = {mapped(k) for k in ("cash.cash", "cash.bank", "cash.instapay", "cash.wallet")}
        payable = -reports.balance_of([mapped("supply.payable")], f.end)
    except FinanceError:
        cash_accounts, payable = set(), ZERO
    by_head = {}
    for row in period.filter(account__kind=Account.EXPENSE).values("account__parent__name_ar", "account__parent__name_en") \
            .annotate(d=Sum("debit"), c=Sum("credit")):
        from django.utils.translation import get_language
        name = row["account__parent__name_en"] if (get_language() or "").startswith("en") and row["account__parent__name_en"] \
            else row["account__parent__name_ar"]
        by_head[name or "—"] = (row["d"] or ZERO) - (row["c"] or ZERO)
    funds = [(r["fund"].code if r["fund"] else "—", r["closing"]) for r in reports.fund_balances(f.start, f.end)]
    return {
        "kpis": [
            {"label": _("Cash and bank now"), "value": reports.balance_of(cash_accounts, f.end), "money": True},
            {"label": _("Income in period"), "value": income_v, "money": True},
            {"label": _("Expenses in period"), "value": expense_v, "money": True},
            {"label": _("Surplus / (deficit)"), "value": income_v - expense_v, "money": True},
            {"label": _("Owed to suppliers"), "value": payable, "money": True},
            {"label": _("Journals waiting for approval"),
             "value": JournalEntry.objects.filter(status=JournalEntry.PENDING).count()},
            {"label": _("Payments waiting"), "value": Payment.objects.filter(
                status__in=(Payment.PENDING, Payment.APPROVED)).count()},
            {"label": _("Posting problems"), "value": PostingIssue.objects.filter(resolved_at__isnull=True).count()},
        ],
        "expenses": bar_rows(sorted(by_head.items(), key=lambda kv: -kv[1])),
        "funds": bar_rows(sorted(funds, key=lambda kv: -kv[1])),
        "filters": ("funds", "departments"),
    }


SECTIONS = [(finance, "finance/_dashboard.html")]
