"""Financial statements from posted journal lines only.

Signs: balances are shown in each account's natural direction (assets and expenses as debit
balances, the rest as credit balances), so totals read the way an accountant expects.
"""
from datetime import date

from django.db.models import Sum

from core.models import Fund

from .models import ZERO, Account, JournalEntry, JournalLine


def posted(start=None, end=None, fund=None, project=None, department=None):
    qs = JournalLine.objects.filter(entry__status=JournalEntry.POSTED)
    if start:
        qs = qs.filter(entry__date__gte=start)
    if end:
        qs = qs.filter(entry__date__lte=end)
    if fund:
        qs = qs.filter(fund_id=fund)
    if project:
        qs = qs.filter(project_id=project)
    if department:
        qs = qs.filter(department_id=department)
    return qs


def _sums(qs, by="account_id"):
    return {row[by]: (row["d"] or ZERO, row["c"] or ZERO)
            for row in qs.values(by).annotate(d=Sum("debit"), c=Sum("credit"))}


def natural(account, debit, credit):
    return debit - credit if account.debit_nature else credit - debit


def trial_balance(start, end, **dims):
    """Opening (balance-sheet accounts: all history; income/expense: since 1 January), movements, closing."""
    year_start = date(start.year, 1, 1)
    before = _sums(posted(**dims).filter(entry__date__lt=start))
    before_year = _sums(posted(**dims).filter(entry__date__lt=start, entry__date__gte=year_start))
    period = _sums(posted(start, end, **dims))
    rows, totals = [], {"od": ZERO, "oc": ZERO, "d": ZERO, "c": ZERO, "cd": ZERO, "cc": ZERO}
    for acc in Account.objects.filter(postable=True).order_by("code"):
        source = before if acc.kind in (Account.ASSET, Account.LIABILITY, Account.NET_ASSETS) else before_year
        od, oc = source.get(acc.pk, (ZERO, ZERO))
        d, c = period.get(acc.pk, (ZERO, ZERO))
        opening, closing = od - oc, od - oc + d - c
        if not (opening or d or c):
            continue
        row = {"account": acc, "od": max(opening, ZERO), "oc": max(-opening, ZERO), "d": d, "c": c,
               "cd": max(closing, ZERO), "cc": max(-closing, ZERO)}
        rows.append(row)
        for k in totals:
            totals[k] += row[k]
    return rows, totals


def ledger(account, start, end, **dims):
    from_start = date(start.year, 1, 1) if account.kind in (Account.INCOME, Account.EXPENSE) else None
    qs_before = posted(from_start, None, **dims).filter(account=account, entry__date__lt=start)
    t = qs_before.aggregate(d=Sum("debit"), c=Sum("credit"))
    balance = natural(account, t["d"] or ZERO, t["c"] or ZERO)
    opening = balance
    rows = []
    for line in posted(start, end, **dims).filter(account=account).select_related("entry", "fund", "project") \
            .order_by("entry__date", "entry_id", "id"):
        balance += natural(account, line.debit, line.credit)
        rows.append({"line": line, "balance": balance})
    return opening, rows, balance


FUND_COLUMNS = [(Fund.UNRESTRICTED, "unrestricted"), (Fund.RESTRICTED, "restricted"), (Fund.ZAKAT, "zakat")]


def _by_fund_kind(qs):
    out = {}
    for row in qs.values("account_id", "fund__kind").annotate(d=Sum("debit"), c=Sum("credit")):
        out.setdefault(row["account_id"], {})[row["fund__kind"] or Fund.UNRESTRICTED] = (row["d"] or ZERO, row["c"] or ZERO)
    return out


def _grouped(kind, data):
    """Accounts of one type grouped under their heading, with amounts per fund kind."""
    groups, grand = [], {k: ZERO for k, _ in FUND_COLUMNS} | {"total": ZERO}
    headings = {}
    for acc in Account.objects.filter(kind=kind, postable=True).select_related("parent").order_by("code"):
        cells = {k: natural(acc, *data.get(acc.pk, {}).get(k, (ZERO, ZERO))) for k, _ in FUND_COLUMNS}
        cells["total"] = sum(cells.values(), ZERO)
        if not any(cells.values()):
            continue
        head = acc.parent
        g = headings.get(head.pk if head else None)
        if g is None:
            g = {"heading": head, "rows": [], "sum": {k: ZERO for k in grand}}
            headings[head.pk if head else None] = g
            groups.append(g)
        g["rows"].append({"account": acc, "cells": cells})
        for k in grand:
            g["sum"][k] += cells[k]
            grand[k] += cells[k]
    return groups, grand


def income_statement(start, end, **dims):
    data = _by_fund_kind(posted(start, end, **dims))
    income, income_total = _grouped(Account.INCOME, data)
    expense, expense_total = _grouped(Account.EXPENSE, data)
    surplus = {k: income_total[k] - expense_total[k] for k in income_total}
    return {"income": income, "income_total": income_total, "expense": expense, "expense_total": expense_total,
            "surplus": surplus}


def balance_sheet(as_of):
    data = _by_fund_kind(posted(end=as_of))
    assets, assets_total = _grouped(Account.ASSET, data)
    # contra accounts (accumulated depreciation) are asset accounts with credit balances: they reduce assets
    liabilities, liabilities_total = _grouped(Account.LIABILITY, data)
    net_assets, net_total = _grouped(Account.NET_ASSETS, data)
    _inc, inc_total = _grouped(Account.INCOME, data)
    _exp, exp_total = _grouped(Account.EXPENSE, data)
    surplus = {k: inc_total[k] - exp_total[k] for k in inc_total}
    funds_total = {k: net_total[k] + surplus[k] for k in net_total}
    return {"assets": assets, "assets_total": assets_total, "liabilities": liabilities,
            "liabilities_total": liabilities_total, "net_assets": net_assets, "surplus": surplus,
            "funds_total": funds_total,
            "check": assets_total["total"] - liabilities_total["total"] - funds_total["total"]}


def fund_balances(start, end):
    """Per fund: balance at start, income, expenses, balance at end (income − expense + net-asset entries)."""
    def per_fund(qs):
        out = {}
        for row in qs.filter(account__kind__in=(Account.INCOME, Account.EXPENSE, Account.NET_ASSETS)) \
                .values("fund_id", "account__kind").annotate(d=Sum("debit"), c=Sum("credit")):
            out.setdefault(row["fund_id"], {})[row["account__kind"]] = (row["d"] or ZERO, row["c"] or ZERO)
        return out

    before, during = per_fund(posted().filter(entry__date__lt=start)), per_fund(posted(start, end))
    rows = []
    for fund in list(Fund.objects.order_by("code")) + [None]:
        key = fund.pk if fund else None
        b, p = before.get(key, {}), during.get(key, {})

        def credit_minus_debit(src, kind):
            d, c = src.get(kind, (ZERO, ZERO))
            return c - d

        opening = sum((credit_minus_debit(b, k) for k in (Account.INCOME, Account.EXPENSE, Account.NET_ASSETS)), ZERO)
        income = credit_minus_debit(p, Account.INCOME)
        expense = -credit_minus_debit(p, Account.EXPENSE)
        other = credit_minus_debit(p, Account.NET_ASSETS)
        if fund is None and not (opening or income or expense or other):
            continue
        rows.append({"fund": fund, "opening": opening, "income": income, "expense": expense, "other": other,
                     "closing": opening + income - expense + other})
    return rows


def balance_of(accounts, as_of=None):
    """Debit-minus-credit balance of some accounts."""
    t = posted(end=as_of).filter(account__in=accounts).aggregate(d=Sum("debit"), c=Sum("credit"))
    return (t["d"] or ZERO) - (t["c"] or ZERO)

