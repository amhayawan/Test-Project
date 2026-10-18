"""Leave: rules sign-off, day counting, balances, limits, line-manager approval, payroll effect.

Day counts below are SAMPLE values for testing only; real values are entered by HR and
signed off by the labour-law specialist. Weekend is the default Friday + Saturday.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory
from django.utils import timezone

from approvals import services
from hr import leave, payroll
from hr.models import (LeaveAdjustment, LeaveEntitlement, LeaveRequest, LeaveType, PayrollRun, PublicHoliday)
from test_hr import hire, org, sample_rules  # noqa: F401  (org is a fixture)

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture(autouse=True)
def _english():
    from django.utils import translation
    with translation.override("en"):     # match error texts in English; pages still render per user
        yield


@pytest.fixture
def rules(org, make_user):
    """Sample rules entered by the HR manager and signed off by the specialist."""
    specialist = make_user("sara", "labour_specialist")
    annual = LeaveType.objects.get(code="ANNUAL")
    LeaveEntitlement.objects.create(leave_type=annual, min_service_months=6, days_per_year=D(15))
    LeaveEntitlement.objects.create(leave_type=annual, min_service_months=12, days_per_year=D(21))
    LeaveEntitlement.objects.create(leave_type=annual, min_service_months=0, min_age=50, days_per_year=D(30))
    LeaveType.objects.filter(code="CASUAL").update(max_per_request=D(2), max_per_year=D(6))
    LeaveType.objects.filter(code="PERMIT").update(max_per_month=D(4))
    LeaveType.objects.filter(code="UNPAID").update(calendar_days=True)
    LeaveType.objects.filter(code="MATERNITY").update(calendar_days=True, max_times_in_service=3)
    LeaveType.objects.update(changed_by=org["hr_manager"], verified_by=specialist, verified_at=timezone.now())
    org["specialist"] = specialist
    return org


def employee_with_manager(org, make_user, **extra):
    boss = hire(org, nid="28001011234567", hired=date(2020, 1, 1))
    boss.user = make_user("boss")
    boss.save()
    emp = hire(org, nid="29001011234567", hired=date(2024, 1, 1), manager=boss, **extra)
    emp.user = make_user("worker")
    emp.save()
    return emp, boss


def ask(emp, code, start, end, hours=None, by=None):
    req = LeaveRequest(employee=emp, leave_type=LeaveType.objects.get(code=code), start_date=start, end_date=end,
                       hours=hours, requested_by=by)
    req.full_clean()
    req.save()
    return req


def test_rules_need_sign_off_by_someone_else(org, make_user):
    specialist = make_user("sara", "labour_specialist", staff=True)
    emp = hire(org)
    with pytest.raises(ValidationError, match="signed off"):
        ask(emp, "ANNUAL", date(2026, 3, 1), date(2026, 3, 2))

    model_admin = site._registry[LeaveType]
    rf = RequestFactory()
    for user in (org["hr_manager"], specialist):
        request = rf.post("/")
        request.user = user
        request._messages = type("M", (), {"add": lambda *a, **k: None})()
        if user is specialist:
            LeaveType.objects.filter(code="ANNUAL").update(changed_by=specialist)   # she edited it herself
            model_admin.mark_verified(request, LeaveType.objects.filter(code="ANNUAL"))
            assert not LeaveType.objects.get(code="ANNUAL").is_verified
            LeaveType.objects.filter(code="ANNUAL").update(changed_by=org["hr_manager"])
        model_admin.mark_verified(request, LeaveType.objects.filter(code="ANNUAL"))
    annual = LeaveType.objects.get(code="ANNUAL")
    assert annual.is_verified and annual.verified_by == specialist          # HR manager could not; Sara could

    request = rf.post("/")
    request.user = org["hr_manager"]
    model_admin.save_model(request, annual, None, True)                     # any edit removes the sign-off
    assert not LeaveType.objects.get(code="ANNUAL").is_verified


def test_counting_balances_and_limits(rules, make_user):
    emp, _boss = employee_with_manager(rules, make_user, birth_date=date(1990, 5, 5))
    PublicHoliday.objects.create(date=date(2026, 3, 3), name_ar="عطلة تجريبية")
    # Sun 1 Mar → Sun 8 Mar 2026: 8 days − Fri/Sat − 1 holiday = 5
    req = ask(emp, "ANNUAL", date(2026, 3, 1), date(2026, 3, 8))
    assert req.amount == D(5)
    assert leave.entitlement(emp, LeaveType.objects.get(code="ANNUAL"), date(2026, 3, 1)) == D(21)

    services.submit(req, emp.user)
    b = leave.balance(emp, LeaveType.objects.get(code="ANNUAL"), 2026, date(2026, 3, 1))
    assert (b["entitled"], b["pending"], b["available"]) == (D(21), D(5), D(16))

    with pytest.raises(ValidationError, match="overlap"):
        ask(emp, "CASUAL", date(2026, 3, 2), date(2026, 3, 2))
    with pytest.raises(ValidationError, match="At most 2"):
        ask(emp, "CASUAL", date(2026, 4, 5), date(2026, 4, 7))
    casual = ask(emp, "CASUAL", date(2026, 4, 5), date(2026, 4, 6))        # taken from the annual balance
    services.submit(casual, emp.user)
    assert leave.balance(emp, LeaveType.objects.get(code="ANNUAL"), 2026, date(2026, 4, 5))["available"] == D(14)

    with pytest.raises(ValidationError, match="Not enough"):
        ask(emp, "ANNUAL", date(2026, 5, 3), date(2026, 5, 28))           # 20 working days > 14 left
    LeaveAdjustment.objects.create(employee=emp, leave_type=LeaveType.objects.get(code="ANNUAL"), year=2026,
                                   days=D(6), reason="رصيد مرحّل")
    ask(emp, "ANNUAL", date(2026, 5, 3), date(2026, 5, 28))                # 14 + 6 carried over = 20

    with pytest.raises(ValidationError, match="Monthly limit"):
        ask(emp, "PERMIT", date(2026, 6, 1), date(2026, 6, 1), hours=D(5))
    ask(emp, "PERMIT", date(2026, 6, 1), date(2026, 6, 1), hours=D(2))
    with pytest.raises(ValidationError, match="does not apply"):
        ask(emp, "MATERNITY", date(2026, 7, 1), date(2026, 7, 10))        # gender not set to female
    with pytest.raises(ValidationError, match="year end"):
        ask(emp, "ANNUAL", date(2026, 12, 29), date(2027, 1, 3))


def test_new_joiner_and_age_rule(rules):
    young = hire(rules, nid="29501011234567", hired=date(2026, 1, 1), birth_date=date(1995, 1, 1))
    older = hire(rules, nid="27501011234567", hired=date(2026, 1, 1), birth_date=date(1975, 1, 1))
    annual = LeaveType.objects.get(code="ANNUAL")
    assert leave.entitlement(young, annual, date(2026, 3, 1)) == 0          # under 6 months
    assert leave.entitlement(young, annual, date(2026, 8, 1)) == 15
    assert leave.entitlement(older, annual, date(2026, 3, 1)) == 30         # age line
    with pytest.raises(ValidationError, match="Not enough"):
        ask(young, "ANNUAL", date(2026, 3, 1), date(2026, 3, 2))


def test_line_manager_approves_not_hr_or_self(rules, make_user):
    emp, boss = employee_with_manager(rules, make_user)
    req = services.submit(ask(emp, "ANNUAL", date(2026, 3, 1), date(2026, 3, 2)), emp.user)
    assert not services.can_act(req, emp.user)
    assert not services.can_act(req, rules["hr_manager"])                  # it is the manager's decision
    assert req in services.inbox(boss.user)
    services.decide(req, boss.user, "approve")
    assert LeaveRequest.objects.get(pk=req.object_id).status == LeaveRequest.APPROVED

    boss.user.is_active = False                                            # no usable manager → HR manager
    boss.user.save()
    req2 = services.submit(ask(emp, "ANNUAL", date(2026, 4, 5), date(2026, 4, 5)), emp.user)
    assert services.can_act(req2, rules["hr_manager"])
    services.cancel(LeaveRequest.objects.get(pk=req2.object_id), emp.user)
    assert LeaveRequest.objects.get(pk=req2.object_id).status == LeaveRequest.CANCELLED


def test_sick_leave_needs_a_document_and_my_leave_page(rules, make_user):
    emp, boss = employee_with_manager(rules, make_user)
    c = Client()
    c.force_login(emp.user)
    page = c.get("/hr/my-leave/")
    assert page.status_code == 200 and "21" in page.content.decode()
    r = c.post("/hr/my-leave/", {"leave_type": LeaveType.objects.get(code="SICK").pk,
                                 "start_date": "2026-03-01", "end_date": "2026-03-02"})
    assert r.status_code == 200 and not LeaveRequest.objects.exists()       # refused: no certificate
    from django.core.files.uploadedfile import SimpleUploadedFile
    pdf = SimpleUploadedFile("cert.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    r = c.post("/hr/my-leave/", {"leave_type": LeaveType.objects.get(code="SICK").pk,
                                 "start_date": "2026-03-01", "end_date": "2026-03-02", "document": pdf})
    assert r.status_code == 302
    req = LeaveRequest.objects.get()
    assert req.status == LeaveRequest.PENDING and req.requested_by == emp.user
    c.force_login(boss.user)
    assert "cert" not in c.get("/hr/my-leave/").content.decode()            # boss sees only their own page
    assert c.get("/approvals/").status_code == 200


def test_unpaid_leave_is_deducted_in_payroll(rules, make_user):
    sample_rules()
    emp, boss = employee_with_manager(rules, make_user)
    req = services.submit(ask(emp, "UNPAID", date(2026, 3, 10), date(2026, 3, 12)), emp.user)   # 3 calendar days
    services.decide(req, boss.user, "approve")
    run = payroll.calculate(PayrollRun.objects.create(year=2026, month=3), rules["payroll"])
    s = run.payslips.get(employee=emp)
    line = next(l for l in s.lines if l["code"] == "LEAVE")
    assert D(line["amount"]) == D("967.74")                                # 10000 / 31 × 3
    assert s.insurable_wage == D("9032.26")
    assert s.net < D("8000")

    run.status = PayrollRun.APPROVED
    run.save()
    with pytest.raises(ValidationError, match="already approved"):
        ask(emp, "UNPAID", date(2026, 3, 20), date(2026, 3, 22))


def test_hr_dashboard_shows_who_is_away(rules, make_user):
    emp, boss = employee_with_manager(rules, make_user)
    today = timezone.localdate()
    LeaveEntitlement.objects.create(leave_type=LeaveType.objects.get(code="ANNUAL"), min_service_months=0,
                                    days_per_year=D(400))
    req = LeaveRequest(employee=emp, leave_type=LeaveType.objects.get(code="UNPAID"), start_date=today,
                       end_date=today, status=LeaveRequest.APPROVED)
    req.save()
    c = Client()
    c.force_login(rules["hr_manager"])
    html = c.get("/").content.decode()
    assert emp.name_ar in html and LeaveType.objects.get(code="UNPAID").name_ar in html
    c.force_login(rules["executive"])
    html = c.get("/").content.decode()
    assert emp.name_ar in html and LeaveType.objects.get(code="UNPAID").name_ar not in html   # no reason shown
