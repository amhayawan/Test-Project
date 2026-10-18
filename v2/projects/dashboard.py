"""Project section of the dashboard: management sees all projects, a project manager only own."""
from django.utils.translation import gettext_lazy as _

from core.models import Project
from dashboards.widgets import bar_rows

from .models import ZERO
from .services import summary, visible_projects


def projects(user, f):
    if not user.has_perm("projects.view_projectprofile"):
        return None
    qs = visible_projects(user).exclude(status=Project.CLOSED)
    if f.project:
        qs = qs.filter(pk=f.project)
    if f.department:
        qs = qs.filter(department_id=f.department)
    qs = list(qs)
    whole = [summary(p) for p in qs]
    period = {p.pk: summary(p, f.start, f.end) for p in qs}
    budget = sum((r["budget"] for r in whole), ZERO)
    actual_all = sum((r["actual"] for r in whole), ZERO)
    return {
        "kpis": [
            {"label": _("Active projects"), "value": sum(1 for p in qs if p.status == Project.ACTIVE)},
            {"label": _("Approved budgets"), "value": budget, "money": True},
            {"label": _("Spent in period"), "value": sum((r["actual"] for r in period.values()), ZERO), "money": True},
            {"label": _("Budget spent to date (%)"), "value": round(float(actual_all / budget * 100)) if budget else 0},
            {"label": _("Projects at risk"), "value": sum(1 for r in whole if r["rag"] == "red")},
            {"label": _("Overdue tasks"), "value": sum(r["overdue_tasks"] for r in whole)},
        ],
        "by_project": bar_rows(sorted(((p.code, period[p.pk]["actual"]) for p in qs), key=lambda kv: -kv[1])),
        "at_risk": [r for r in whole if r["rag"] != "green"][:8],
        "filters": ("departments", "projects"),
    }


SECTIONS = [(projects, "projects/_dashboard.html")]
