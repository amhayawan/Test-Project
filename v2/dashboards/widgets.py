"""Dashboard sections. Each section checks the permission it needs and returns None when the
user's role may not see it, so every role gets its own dashboard from the same page.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.roles import ROLES, role_label
from accounts.sod import conflicts
from approvals.models import ApprovalAction, ApprovalRequest
from approvals.services import inbox
from cases.models import Aid, Beneficiary, CaseNeed
from core.models import AuditLog
from crm.models import Donation, Sponsorship

ZERO = Decimal(0)


def _aware(d, end=False):
    return timezone.make_aware(datetime.combine(d, time.max if end else time.min))


def pct_change(current, previous):
    if not previous:
        return None
    return round((float(current) - float(previous)) / float(previous) * 100, 1)


def bar_rows(pairs, labels=None):
    """[(key, value)] -> rows with a 0-100 width for simple horizontal bars."""
    pairs = [(k, Decimal(v or 0)) for k, v in pairs]
    top = max([v for _, v in pairs] + [ZERO]) or Decimal(1)
    return [{"label": (labels or {}).get(k, k), "value": v, "pct": round(float(v / top * 100), 1)} for k, v in pairs]


# ---------------------------------------------------------------- filtered querysets

def donations(f, start=None, end=None):
    qs = Donation.objects.filter(donation_date__range=(start or f.start, end or f.end))
    if f.campaign:
        qs = qs.filter(campaign_id=f.campaign)
    if f.fund:
        qs = qs.filter(fund_id=f.fund)
    if f.project:
        qs = qs.filter(Q(campaign__project_id=f.project) | Q(beneficiary__project_id=f.project))
    if f.department:
        qs = qs.filter(Q(campaign__project__department_id=f.department) | Q(beneficiary__department_id=f.department))
    return qs


def cases(f, user):
    qs = Beneficiary.objects.visible_to(user)
    if f.department:
        qs = qs.filter(department_id=f.department)
    if f.project:
        qs = qs.filter(project_id=f.project)
    return qs


def aid_delivered(f, start=None, end=None):
    qs = Aid.objects.filter(status=Aid.DELIVERED, delivered_on__range=(start or f.start, end or f.end))
    if f.fund:
        qs = qs.filter(fund_id=f.fund)
    if f.department:
        qs = qs.filter(beneficiary__department_id=f.department)
    if f.project:
        qs = qs.filter(beneficiary__project_id=f.project)
    return qs


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


# ---------------------------------------------------------------- sections

def fundraising(user, f):
    if not user.has_perm("crm.view_donation"):
        return None
    cur = donations(f)
    prev = donations(f, *f.previous)
    total, prev_total = _sum(cur, "amount"), _sum(prev, "amount")
    donors_in_period = cur.values("donor").distinct().count()
    new_donors = (cur.values("donor").distinct()
                  .exclude(donor__in=Donation.objects.filter(donation_date__lt=f.start).values("donor")).count())
    trend = [{"label": label, "values": [_sum(donations(f, s, e), "amount")]} for label, s, e in f.buckets()]
    purpose_labels = dict(Donation.PURPOSES)
    method_labels = dict(Donation.METHODS)
    section = {
        "kpis": [
            {"label": _("Donations"), "value": total, "money": True, "change": pct_change(total, prev_total)},
            {"label": _("Number of donations"), "value": cur.count(), "change": pct_change(cur.count(), prev.count())},
            {"label": _("Donors who gave"), "value": donors_in_period},
            {"label": _("New donors"), "value": new_donors},
            {"label": _("Average gift"), "value": (total / cur.count()) if cur.count() else ZERO, "money": True},
        ],
        "trend": {"series": [_("Donations")], "rows": trend},
        "by_purpose": bar_rows(cur.values_list("purpose").annotate(t=Sum("amount")).order_by("-t"), purpose_labels),
        "by_method": bar_rows(cur.values_list("method").annotate(t=Sum("amount")).order_by("-t"), method_labels),
        "campaigns": [],
        "top_donors": [],
    }
    from crm.models import Campaign
    for c in Campaign.objects.filter(Q(end_date__isnull=True) | Q(end_date__gte=f.start), start_date__lte=f.end):
        raised = _sum(c.donations.all(), "amount")
        section["campaigns"].append({"name": c.name, "raised": raised, "target": c.target,
                                     "pct": round(min(100.0, float(raised / c.target * 100)), 1) if c.target else None})
    if user.has_perm("crm.view_donor"):
        section["top_donors"] = list(cur.values("donor__name").annotate(t=Sum("amount"), n=Count("id"))
                                     .order_by("-t")[:8])
    return section


def sponsorships(user, f):
    if not (user.has_perm("crm.view_sponsorship") and user.has_perm("cases.view_case_funding")):
        return None
    active = Sponsorship.objects.filter(status=Sponsorship.ACTIVE)
    if f.department:
        active = active.filter(beneficiary__department_id=f.department)
    if f.project:
        active = active.filter(beneficiary__project_id=f.project)
    collected = _sum(donations(f).filter(sponsorship__isnull=False), "amount")
    late = sorted((s for s in active.select_related("donor", "beneficiary") if s.arrears > 0),
                  key=lambda s: -s.arrears)
    return {
        "kpis": [
            {"label": _("Active sponsorships"), "value": active.count()},
            {"label": _("Committed per month"), "value": _sum(active, "monthly_amount"), "money": True},
            {"label": _("Collected in period"), "value": collected, "money": True},
            {"label": _("Total arrears now"), "value": sum((s.arrears for s in late), ZERO), "money": True},
        ],
        "late": late[:8],
    }


def case_management(user, f):
    if not user.has_perm("cases.view_all_cases"):
        return None
    qs = cases(f, user)
    registered = qs.filter(created_at__range=(_aware(f.start), _aware(f.end, True)))
    case_ct_requests = ApprovalRequest.objects.filter(doc_type="cases.case")
    decided = case_ct_requests.filter(closed_at__range=(_aware(f.start), _aware(f.end, True)))
    if f.department or f.project:
        decided = decided.filter(object_id__in=qs.values("pk"))
    spans = [(r.closed_at - r.created_at).total_seconds() for r in decided.only("closed_at", "created_at")]
    turnaround = timedelta(seconds=sum(spans) / len(spans)) if spans else None
    categories = dict(Beneficiary.CATEGORIES)
    needs = CaseNeed.objects.filter(is_open=True, beneficiary__in=qs.filter(status=Beneficiary.APPROVED))
    unfunded = [n for n in needs.select_related("beneficiary") if n.funding_state != "funded"]
    workload = []
    User = get_user_model()
    for r in User.objects.filter(assigned_cases__in=qs).distinct():
        mine = qs.filter(researcher=r)
        workload.append({"name": r.display_name,
                         "researching": mine.filter(status=Beneficiary.UNDER_STUDY).count(),
                         "waiting": mine.filter(status=Beneficiary.RECOMMENDED).count(),
                         "approved": mine.filter(status=Beneficiary.APPROVED).count()})
    workload.sort(key=lambda w: -(w["researching"] + w["waiting"]))
    return {
        "pipeline": [
            {"label": _("Not assigned"), "value": qs.filter(status=Beneficiary.UNDER_STUDY, researcher__isnull=True).count()},
            {"label": _("Being researched"), "value": qs.filter(status=Beneficiary.UNDER_STUDY, researcher__isnull=False).count()},
            {"label": _("Awaiting approval"), "value": qs.filter(status=Beneficiary.RECOMMENDED).count()},
            {"label": _("Approved"), "value": qs.filter(status=Beneficiary.APPROVED).count()},
            {"label": _("Rejected / suspended"), "value": qs.filter(status__in=(Beneficiary.REJECTED, Beneficiary.SUSPENDED)).count()},
        ],
        "kpis": [
            {"label": _("New cases registered"), "value": registered.count()},
            {"label": _("Cases approved"), "value": decided.filter(status=ApprovalRequest.APPROVED).count()},
            {"label": _("Cases rejected"), "value": decided.filter(status=ApprovalRequest.REJECTED).count()},
            {"label": _("Returned to researcher"), "value": decided.filter(status=ApprovalRequest.RETURNED).count()},
            {"label": _("Average days to decision"),
             "value": round(turnaround.total_seconds() / 86400, 1) if turnaround else "—"},
        ],
        "by_category": bar_rows(registered.values_list("category").annotate(n=Count("id")).order_by("-n"), categories),
        "needs": {"count": len(unfunded), "urgent": sum(1 for n in unfunded if n.priority == "urgent"),
                  "needed": sum((n.amount_needed for n in unfunded), ZERO) if user.has_perm("cases.view_case_funding") else None},
        "workload": workload,
    }


def my_cases(user, f):
    """For researchers: their own queue."""
    if user.has_perm("cases.view_all_cases") or not user.has_perm("cases.view_beneficiary"):
        return None
    qs = Beneficiary.objects.visible_to(user)
    researching = qs.filter(status=Beneficiary.UNDER_STUDY)
    returned_ids = set(ApprovalRequest.objects.filter(doc_type="cases.case", status=ApprovalRequest.RETURNED,
                                                      object_id__in=researching.values("pk"))
                       .values_list("object_id", flat=True))
    mine = ApprovalRequest.objects.filter(doc_type="cases.case", maker=user,
                                          created_at__range=(_aware(f.start), _aware(f.end, True)))
    return {
        "kpis": [
            {"label": _("My cases being researched"), "value": researching.count()},
            {"label": _("Returned to me for changes"), "value": len(returned_ids)},
            {"label": _("Waiting for approval"), "value": qs.filter(status=Beneficiary.RECOMMENDED).count()},
            {"label": _("Submitted in period"), "value": mine.count()},
            {"label": _("Approved in period"), "value": mine.filter(status=ApprovalRequest.APPROVED).count()},
        ],
        "todo": [{"case": c, "returned": c.pk in returned_ids, "missing": c.research_missing}
                 for c in researching.order_by("created_at")[:15]],
    }


def aid(user, f):
    if not user.has_perm("cases.view_aid"):
        return None
    cur, prev = aid_delivered(f), aid_delivered(f, *f.previous)
    pending = Aid.objects.filter(status=Aid.PENDING)
    types = dict(Aid.TYPES)
    total = _sum(cur, "value")
    return {
        "kpis": [
            {"label": _("Aid delivered"), "value": total, "money": True, "change": pct_change(total, _sum(prev, "value"))},
            {"label": _("Families helped"), "value": cur.values("beneficiary").distinct().count()},
            {"label": _("Aid awaiting approval"), "value": _sum(pending, "value"), "money": True},
        ],
        "by_type": bar_rows(cur.values_list("aid_type").annotate(t=Sum("value")).order_by("-t"), types),
    }


def overview(user, f):
    """Money in vs money out, for management roles that see both."""
    if not (user.has_perm("crm.view_donation") and user.has_perm("cases.view_aid")
            and user.has_perm("cases.view_all_cases")):
        return None
    rows = [{"label": label, "values": [_sum(donations(f, s, e), "amount"), _sum(aid_delivered(f, s, e), "value")]}
            for label, s, e in f.buckets()]
    return {"series": [_("Donations"), _("Aid delivered")], "rows": rows,
            "totals": [sum((r["values"][0] for r in rows), ZERO), sum((r["values"][1] for r in rows), ZERO)]}


def approvals(user, f):
    waiting = inbox(user)
    mine = ApprovalRequest.objects.filter(maker=user, status=ApprovalRequest.PENDING)
    decided_by_me = ApprovalAction.objects.filter(actor=user, at__range=(_aware(f.start), _aware(f.end, True)))
    return {"waiting": waiting[:8], "waiting_count": len(waiting), "mine_pending": mine.count(),
            "decided": decided_by_me.count()}


def administration(user, f):
    if not user.has_perm("accounts.view_user"):
        return None
    User = get_user_model()
    period = AuditLog.objects.filter(at__range=(_aware(f.start), _aware(f.end, True)))
    by_role = [(role_label(code), User.objects.filter(groups__name=code, is_active=True).count()) for code in ROLES]
    return {
        "kpis": [
            {"label": _("Active users"), "value": User.objects.filter(is_active=True).count()},
            {"label": _("Sign-ins"), "value": period.filter(action="login").count()},
            {"label": _("Failed sign-ins"), "value": period.filter(action="login_failed").count()},
            {"label": _("Accounts locked now"), "value": User.objects.filter(locked_until__gt=timezone.now()).count()},
            {"label": _("Recorded changes"), "value": period.filter(action__in=("create", "update", "delete")).count()},
        ],
        "by_role": bar_rows(by_role),
        "conflicts": conflicts(),
    }


def human_resources(user, f):
    if not user.has_perm("hr.view_employee"):
        return None
    from hr.models import Contract, Employee, PayrollRun, Position
    from hr.payroll import cost_by
    from core.models import Attachment
    from django.contrib.contenttypes.models import ContentType
    staff = Employee.objects.current()
    if f.department:
        staff = staff.filter(department_id=f.department)
    soon = timezone.localdate() + timedelta(days=60)
    ending = Contract.objects.filter(status=Contract.ACTIVE, end_date__isnull=False,
                                     end_date__range=(timezone.localdate(), soon), employee__in=staff)
    docs = Attachment.objects.filter(content_type__in=ContentType.objects.get_for_models(Employee, Contract).values(),
                                     expires_on__isnull=False, expires_on__lte=soon)
    vacancies = sum(max(p.headcount - p.filled, 0) for p in Position.objects.filter(is_active=True))
    by_dept = staff.values_list("department__code").annotate(n=Count("id")).order_by("-n")
    section = {
        "kpis": [
            {"label": _("Employees now"), "value": staff.count()},
            {"label": _("Joined in period"), "value": Employee.objects.filter(hire_date__range=(f.start, f.end)).count()},
            {"label": _("Left in period"), "value": Employee.objects.filter(end_date__range=(f.start, f.end)).count()},
            {"label": _("Vacant posts"), "value": vacancies},
            {"label": _("Contracts ending within 60 days"), "value": ending.count()},
            {"label": _("Documents expiring within 60 days"), "value": docs.count()},
        ],
        "by_department": bar_rows(by_dept),
        "ending": ending.select_related("employee").order_by("end_date")[:8],
        "payroll": None,
    }
    if user.has_perm("hr.view_salary"):
        runs = [r for r in PayrollRun.objects.filter(status__in=(PayrollRun.APPROVED, PayrollRun.PAID))
                if f.start <= date(r.year, r.month, 1) <= f.end]
        per_dept = {}
        for r in runs:
            for k, v in cost_by(r, "department").items():
                per_dept[k] = per_dept.get(k, ZERO) + v
        section["payroll"] = {
            "kpis": [
                {"label": _("Payroll cost in period"), "value": sum((r.total_cost for r in runs), ZERO), "money": True},
                {"label": _("Net salaries paid"), "value": sum((r.total_net for r in runs), ZERO), "money": True},
                {"label": _("Payroll months approved"), "value": len(runs)},
            ],
            "by_department": bar_rows(sorted(per_dept.items(), key=lambda kv: -kv[1])),
        }
    return section


SECTIONS = ["overview", "approvals", "my_cases", "case_management", "fundraising", "sponsorships", "aid",
            "human_resources", "administration"]


def build(user, f):
    funcs = {"overview": overview, "approvals": approvals, "my_cases": my_cases, "case_management": case_management,
             "fundraising": fundraising, "sponsorships": sponsorships, "aid": aid,
             "human_resources": human_resources, "administration": administration}
    return {name: funcs[name](user, f) for name in SECTIONS}
