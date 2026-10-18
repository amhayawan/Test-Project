"""Projects: budget maker-checker, actuals from finance / cases / payroll, scoping, risk flag."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone, translation

from approvals import services
from cases.models import Aid, Beneficiary
from core.models import Project
from crm.models import Campaign, Donation, Donor
from finance import posting
from finance.models import Account
from hr import payroll
from hr.models import Assignment, PayrollRun
from projects.models import BudgetLine, ProjectProfile, Task
from projects.services import rag, summary, visible_projects
from test_hr import hire, org, sample_rules  # noqa: F401

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


@pytest.fixture
def proj(org, make_user):
    pm = make_user("pm", "project_manager", staff=True)
    other_pm = make_user("pm2", "project_manager", staff=True)
    project = org["project"]
    project.manager, project.status = pm, Project.ACTIVE
    project.save()
    other = Project.objects.create(code="EDU", name_ar="تعليم", department=org["prog"], manager=other_pm,
                                   status=Project.ACTIVE)
    org.update(pm=pm, other_pm=other_pm, other=other, fm=make_user("fm", "finance_manager"))
    return org


def acc(code):
    return Account.objects.get(code=code)


def test_budget_needs_approval_and_locks(proj):
    profile = ProjectProfile.objects.create(project=proj["project"])
    with pytest.raises(ValidationError, match="Add budget lines"):
        services.submit(profile, proj["pm"])
    BudgetLine.objects.create(profile=profile, account=acc("5108"), amount=D(40000))
    BudgetLine.objects.create(profile=profile, account=acc("5201"), amount=D(60000))
    with pytest.raises(ValidationError, match="expense"):
        BudgetLine(profile=profile, account=acc("1101"), amount=D(1)).full_clean()
    req = services.submit(profile, proj["pm"])
    assert req.amount == D(100000) and not services.can_act(req, proj["pm"])
    with pytest.raises(ValidationError):
        BudgetLine.objects.create(profile=profile, account=acc("5305"), amount=D(5))   # locked while pending
    services.decide(req, proj["fm"], "approve")
    profile.refresh_from_db()
    assert profile.budget_status == ProjectProfile.APPROVED and profile.approved_total == D(100000)
    profile.reopen()
    assert profile.budget_version == 2 and profile.approved_total == D(100000)       # kept until re-approved
    BudgetLine.objects.create(profile=profile, account=acc("5305"), amount=D(5000))


def test_actuals_come_from_finance_cases_and_payroll(proj):
    project = proj["project"]
    profile = ProjectProfile.objects.create(project=project)
    BudgetLine.objects.create(profile=profile, account=acc("5108"), amount=D(20000))
    ProjectProfile.objects.filter(pk=profile.pk).update(budget_status="approved", approved_total=D(20000))
    project.refresh_from_db()

    entry = posting._create(date(2026, 3, 5), "Supplies", "manual", [
        {"account": acc("5108"), "debit": D(3000), "credit": D(0), "project": project},
        {"account": acc("1102"), "debit": D(0), "credit": D(3000)}])
    entry.post()
    case = Beneficiary.objects.create(name="حالة", status=Beneficiary.APPROVED, project=project)
    aid = Aid.objects.create(beneficiary=case, aid_type="food", value=D(1000), project=project, status=Aid.APPROVED)
    aid.mark_delivered(date(2026, 3, 6))
    camp = Campaign.objects.create(code="C1", name="حملة", start_date=date(2026, 3, 1), project=project)
    Donation.objects.create(donor=Donor.objects.create(name="متبرع"), amount=D(5000), method="bank",
                            campaign=camp, donation_date=date(2026, 3, 2))
    sample_rules()
    emp = hire(proj)
    Assignment.objects.create(employee=emp, department=proj["prog"], project=project, percent=D(50),
                              start_date=date(2026, 1, 1))
    run = payroll.calculate(PayrollRun.objects.create(year=2026, month=3), proj["payroll"])
    req = services.submit(run, proj["payroll"])
    services.decide(req, proj["hr_manager"], "approve")
    services.decide(req, proj["executive"], "approve")

    s = summary(Project.objects.get(pk=project.pk), detail=True)
    staff = D("5937.50")                                        # 50% of 10,000 + 1,875 employer insurance
    assert s["staff_cost"] == staff
    assert s["actual"] == D(3000) + D(1000) + staff
    assert s["funding"] == D(5000)
    assert s["aid_total"] == D(1000) and s["beneficiaries"] == 1
    supplies = next(r for r in s["by_account"] if r["account"].code == "5108")
    assert supplies["budget"] == D(20000) and supplies["actual"] == D(3000) and supplies["variance"] == D(17000)
    assert len(s["team"]) == 1
    march = summary(Project.objects.get(pk=project.pk), date(2026, 4, 1), date(2026, 4, 30))
    assert march["actual"] == 0                                 # period filter


def test_project_manager_sees_only_own_projects(proj):
    assert list(visible_projects(proj["pm"])) == [proj["project"]]
    assert set(visible_projects(proj["executive"])) == {proj["project"], proj["other"]}
    proj["pm"].scope_projects.add(proj["other"])
    assert set(visible_projects(proj["pm"])) == {proj["project"], proj["other"]}
    proj["pm"].scope_projects.clear()

    c = Client()
    c.force_login(proj["pm"])
    assert c.get(f"/projects/{proj['project'].pk}/").status_code == 200
    assert c.get(f"/projects/{proj['other'].pk}/").status_code == 404
    page = c.get("/projects/").content.decode()
    assert proj["project"].code in page and "EDU" not in page
    dash = c.get("/").content.decode()
    assert "EDU" not in dash and proj["project"].code in dash
    assert c.get("/backoffice/projects/task/").status_code == 200
    c.force_login(proj["executive"])
    page = c.get("/projects/").content.decode()
    assert "EDU" in page and proj["project"].code in page
    assert c.get(f"/projects/{proj['other'].pk}/?period=this_year").status_code == 200
    c.force_login(proj["researcher"])
    assert c.get("/projects/").status_code == 403


def test_progress_and_risk_flag(proj):
    project = proj["project"]
    Task.objects.create(project=project, title="أ", weight=3, status=Task.DONE)
    Task.objects.create(project=project, title="ب", weight=1, percent=0,
                        due=timezone.localdate() - timedelta(days=1))
    s = summary(project)
    assert s["progress"] == 75 and s["overdue_tasks"] == 1
    assert rag(50, 75, project) == "green"
    assert rag(80, 75, project) == "amber"
    assert rag(91, 75, project) == "red"
    project.end_date = timezone.localdate() - timedelta(days=1)
    assert rag(10, 75, project) == "red"                        # late and unfinished
    project.status = Project.CLOSED
    assert rag(10, 75, project) == "green"
