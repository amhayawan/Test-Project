from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, render


from core.models import Department, Fund, Project
from dashboards import filters as flt

from . import reports
from .models import Account, JournalEntry, PostingIssue

PERM = "finance.view_journalline"


def _ctx(request, **extra):
    f = flt.parse(request.GET)
    dims = {"fund": f.fund, "project": f.project, "department": f.department}
    return f, dims, {"f": f, "presets": flt.PRESETS, "funds": Fund.objects.filter(is_active=True),
                     "projects": Project.objects.all(), "departments": Department.objects.filter(is_active=True),
                     **extra}


@login_required
@permission_required(PERM, raise_exception=True)
def index(request):
    return render(request, "finance/index.html", {
        "pending": JournalEntry.objects.filter(status=JournalEntry.PENDING).count(),
        "issues": PostingIssue.objects.filter(resolved_at__isnull=True).count()})


@login_required
@permission_required(PERM, raise_exception=True)
def trial_balance(request):
    f, dims, ctx = _ctx(request, title="trial")
    rows, totals = reports.trial_balance(f.start, f.end, **dims)
    return render(request, "finance/trial_balance.html", {**ctx, "rows": rows, "t": totals})


@login_required
@permission_required(PERM, raise_exception=True)
def ledger(request):
    f, dims, ctx = _ctx(request)
    accounts = Account.objects.filter(postable=True).order_by("code")
    account = get_object_or_404(Account, pk=request.GET["account"]) if request.GET.get("account") else None
    data = reports.ledger(account, f.start, f.end, **dims) if account else None
    return render(request, "finance/ledger.html", {**ctx, "accounts": accounts, "account": account, "data": data})


@login_required
@permission_required(PERM, raise_exception=True)
def income_statement(request):
    f, dims, ctx = _ctx(request)
    return render(request, "finance/income_statement.html", {**ctx, "r": reports.income_statement(f.start, f.end, **dims),
                                                             "columns": reports.FUND_COLUMNS})


@login_required
@permission_required(PERM, raise_exception=True)
def balance_sheet(request):
    f, _dims, ctx = _ctx(request)
    return render(request, "finance/balance_sheet.html", {**ctx, "r": reports.balance_sheet(f.end),
                                                          "columns": reports.FUND_COLUMNS, "as_of": f.end})


@login_required
@permission_required(PERM, raise_exception=True)
def funds(request):
    f, _dims, ctx = _ctx(request)
    return render(request, "finance/funds.html", {**ctx, "rows": reports.fund_balances(f.start, f.end)})



