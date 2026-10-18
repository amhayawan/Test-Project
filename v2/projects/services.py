"""Read-only project figures assembled from finance, case management and HR."""
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Project

from .models import ZERO, weighted_progress

RAG_LABELS = {"red": _("At risk"), "amber": _("Watch"), "green": _("On track")}


def visible_projects(user):
    """Everyone with 'view all projects' sees all; a project manager only own / scoped projects."""
    qs = Project.objects.all()
    if not user.is_authenticated:
        return qs.none()
    if user.has_perm("projects.view_all_projects"):
        return qs
    if not user.has_perm("projects.view_projectprofile"):
        return qs.none()
    return qs.filter(Q(manager=user) | Q(pk__in=user.scope_projects.values("pk"))).distinct()


def _mapped_accounts(*keys):
    from finance.models import FinanceError, mapped
    found = set()
    for key in keys:
        try:
            found.add(mapped(key).pk)
        except FinanceError:
            pass
    return found


def _net(qs, debit_side=True):
    t = qs.aggregate(d=Sum("debit"), c=Sum("credit"))
    d, c = t["d"] or ZERO, t["c"] or ZERO
    return d - c if debit_side else c - d


def budget_total(project):
    profile = getattr(project, "profile", None)
    if profile is None:
        return ZERO
    return profile.approved_total if profile.approved_total else ZERO


def rag(spend_pct, progress, project, today=None):
    today = today or timezone.localdate()
    late = bool(project.end_date and project.end_date < today and project.status != Project.CLOSED and progress < 100)
    if late or spend_pct > progress + 15:
        return "red"
    if spend_pct > progress:
        return "amber"
    return "green"


def summary(project, start=None, end=None, detail=False):
    """Budget, actuals and progress of one project; `start`/`end` limit the actuals to a period."""
    from finance import reports
    from finance.models import Account
    lines = reports.posted(start, end, project=project.pk)
    expense_lines = lines.filter(account__kind=Account.EXPENSE)
    actual = _net(expense_lines)
    staff = _net(expense_lines.filter(account_id__in=_mapped_accounts("payroll.salaries", "payroll.employer_insurance")))
    purchases = _net(expense_lines.filter(account_id__in=_mapped_accounts("supply.expense")))
    funding = _net(lines.filter(account__kind=Account.INCOME), debit_side=False)
    budget = budget_total(project)
    tasks = list(project.tasks.all())
    progress = weighted_progress(tasks)
    spend_pct = round(float(actual / budget * 100)) if budget else (100 if actual else 0)
    today = timezone.localdate()
    data = {
        "project": project, "budget": budget, "actual": actual, "remaining": budget - actual, "spend_pct": spend_pct,
        "progress": progress, "funding": funding, "staff_cost": staff, "purchases": purchases,
        "rag": rag(spend_pct, progress, project, today),
        "overdue_tasks": sum(1 for t in tasks if t.due and t.due < today and t.status != t.DONE),
    }
    data["rag_label"] = RAG_LABELS[data["rag"]]
    if not detail:
        return data
    from cases.models import Aid, Beneficiary
    from hr.models import Assignment
    profile = getattr(project, "profile", None)
    by_account = {}
    for bl in (profile.lines.select_related("account") if profile else []):
        row = by_account.setdefault(bl.account_id, {"account": bl.account, "budget": ZERO, "actual": ZERO})
        row["budget"] += bl.amount
    for row in expense_lines.values("account_id").annotate(d=Sum("debit"), c=Sum("credit")):
        entry = by_account.get(row["account_id"])
        if entry is None:
            entry = by_account[row["account_id"]] = {"account": Account.objects.get(pk=row["account_id"]),
                                                     "budget": ZERO, "actual": ZERO}
        entry["actual"] += (row["d"] or ZERO) - (row["c"] or ZERO)
    rows = sorted(by_account.values(), key=lambda r: r["account"].code)
    for r in rows:
        r["variance"] = r["budget"] - r["actual"]
        r["over"] = r["actual"] > r["budget"]
    aids = Aid.objects.filter(project=project, status=Aid.DELIVERED)
    if start:
        aids = aids.filter(delivered_on__gte=start)
    if end:
        aids = aids.filter(delivered_on__lte=end)
    data.update({
        "profile": profile, "by_account": rows, "draft_total": profile.total() if profile else ZERO,
        "aid_total": aids.aggregate(s=Sum("value"))["s"] or ZERO, "aid_count": aids.count(),
        "beneficiaries": Beneficiary.objects.filter(Q(project=project) | Q(aids__project=project)).distinct().count(),
        "milestones": [{"m": m, "progress": m.progress()} for m in project.milestones.all()],
        "tasks": sorted(tasks, key=lambda t: (t.due is None, t.due)),
        "team": Assignment.objects.filter(project=project).select_related("employee", "department")
                .filter(Q(end_date__isnull=True) | Q(end_date__gte=today)),
    })
    return data

