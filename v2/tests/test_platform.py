from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from approvals import services
from approvals.models import ApprovalRequest
from cases.models import Aid, Beneficiary, CaseNeed
from core.models import Attachment, AuditLog, Fund, next_number
from crm.models import Donation, Donor

pytestmark = pytest.mark.django_db


def research_done(case):
    case.visit_date = timezone.localdate()
    case.zakat_eligible = "yes"
    case.research_findings = "زيارة ميدانية"
    case.recommendation = "قبول"
    case.assessment = "urgent"
    case.save()
    return case


@pytest.fixture
def team(make_user):
    return {
        "researcher": make_user("res1", "researcher"),
        "researcher2": make_user("res2", "researcher"),
        "manager": make_user("manager", "case_manager"),
        "manager2": make_user("manager2", "case_manager"),
        "executive": make_user("director", "executive"),
        "both": make_user("both", "case_manager", "executive"),
        "fund": make_user("fund", "fundraising"),
        "projects": make_user("proj", "projects_officer"),
        "pm": make_user("pm", "project_manager"),
        "pm_exec": make_user("pmx", "project_manager", "executive"),
    }


def test_case_numbering_and_research_gate(team):
    case = Beneficiary.objects.create(name="أسرة", researcher=team["researcher"])
    year = timezone.localdate().year
    assert case.case_no == f"C-{year}-00001"
    with pytest.raises(ValidationError):            # research not complete
        services.submit(case, team["researcher"])
    assert not ApprovalRequest.objects.exists()       # rolled back
    req = services.submit(research_done(case), team["researcher"], note="أوصي بالقبول")
    case.refresh_from_db()
    assert case.status == Beneficiary.RECOMMENDED and req.status == req.PENDING


def test_maker_checker_rules(team):
    case = research_done(Beneficiary.objects.create(name="أسرة", researcher=team["manager"]))
    req = services.submit(case, team["manager"])          # a manager acting as maker
    with pytest.raises(services.ApprovalError):
        services.decide(req, team["manager"], "approve")   # cannot approve own submission
    with pytest.raises(services.ApprovalError):
        services.decide(req, team["researcher"], "approve")  # wrong role
    with pytest.raises(services.ApprovalError):
        services.decide(req, team["manager2"], "reject")   # reason required
    assert req in services.inbox(team["manager2"]) and req not in services.inbox(team["manager"])
    services.decide(req, team["manager2"], "return", "ينقص صورة البطاقة")
    case.refresh_from_db()
    assert case.status == Beneficiary.UNDER_STUDY
    req2 = services.submit(case, team["manager"])
    services.decide(req2, team["manager2"], "approve")
    case.refresh_from_db()
    assert case.status == Beneficiary.APPROVED
    assert {"submit", "return", "approve"} <= set(AuditLog.objects.values_list("action", flat=True))


def test_large_aid_needs_two_different_approvers(team):
    case = research_done(Beneficiary.objects.create(name="حالة", researcher=team["researcher"]))
    services.decide(services.submit(case, team["researcher"]), team["manager"], "approve")
    # the Projects Department requests the aid; its manager approves (and the executive above the limit)
    small = Aid.objects.create(beneficiary=case, value=Decimal("500"), requested_by=team["projects"])
    req = services.submit(small, team["projects"])
    assert req.policy.steps.count() == 1 and not services.can_act(req, team["manager"])
    big = Aid.objects.create(beneficiary=case, value=Decimal("25000"), requested_by=team["projects"])
    req = services.submit(big, team["projects"])
    assert [s.role.name for s in req.policy.steps.all()] == ["project_manager", "executive"]
    with pytest.raises(services.ApprovalError):
        services.decide(req, team["executive"], "approve")      # step 1 is the Projects Department manager's
    services.decide(req, team["pm_exec"], "approve")             # step 1 done by someone with both roles
    with pytest.raises(services.ApprovalError):
        services.decide(req, team["pm_exec"], "approve")        # ...who may not also do step 2
    big.refresh_from_db()
    assert big.status == Aid.PENDING
    services.decide(req, team["executive"], "approve")
    big.refresh_from_db()
    assert big.status == Aid.APPROVED


def test_aid_and_donation_business_rules(team):
    case = Beneficiary.objects.create(name="حالة", researcher=team["researcher"])
    donor = Donor.objects.create(name="متبرع")
    with pytest.raises(ValidationError):
        Aid(beneficiary=case, value=Decimal("100")).full_clean()            # not approved yet
    with pytest.raises(ValidationError):
        Donation(donor=donor, amount=Decimal("100"), beneficiary=case).full_clean()
    case = research_done(case)
    case.zakat_eligible = "no"
    case.save()
    services.decide(services.submit(case, team["researcher"]), team["manager"], "approve")
    case.refresh_from_db()
    with pytest.raises(ValidationError) as err:
        Donation(donor=donor, amount=Decimal("100"), purpose="zakat", beneficiary=case).full_clean()
    assert "purpose" in err.value.message_dict
    zakat_fund = Fund.objects.get(code="ZAK")
    with pytest.raises(ValidationError):
        Aid(beneficiary=case, value=Decimal("100"), fund=zakat_fund).full_clean()
    need = CaseNeed.objects.create(beneficiary=case, need_type="medical", description="عملية",
                                   amount_needed=Decimal("1000"))
    d = Donation(donor=donor, amount=Decimal("1000"), purpose="medical", need=need)
    d.full_clean()
    d.save()
    assert d.beneficiary == case and need.funding_state == "funded"
    with pytest.raises(ValidationError):
        Donation(donor=donor, amount=Decimal("100"), purpose="zakat", fund=Fund.objects.get(code="GEN")).full_clean()


def test_receipt_numbers_are_sequential_per_year(db):
    donor = Donor.objects.create(name="متبرع")
    a = Donation.objects.create(donor=donor, amount=1, donation_date="2026-03-01")
    b = Donation.objects.create(donor=donor, amount=1, donation_date="2026-04-01")
    c = Donation.objects.create(donor=donor, amount=1, donation_date="2027-01-02")
    assert (a.receipt_no, b.receipt_no, c.receipt_no) == ("R-2026-00001", "R-2026-00002", "R-2027-00001")
    assert next_number("voucher", 2026) == "VOUCHER-2026-00001"


def test_audit_trail_records_old_and_new_values(db):
    donor = Donor.objects.create(name="متبرع", phone="0100")
    donor.phone = "0111"
    donor.save()
    entry = AuditLog.objects.filter(action="update", object_id=str(donor.pk)).get()
    assert entry.changes == {"phone": ["0100", "0111"]}
    pk = donor.pk
    donor.delete()
    assert AuditLog.objects.filter(action="delete", object_id=str(pk)).exists()


def test_researchers_see_only_their_cases(team):
    mine = Beneficiary.objects.create(name="حالتي", researcher=team["researcher"])
    Beneficiary.objects.create(name="حالة زميل", researcher=team["researcher2"])
    assert list(Beneficiary.objects.visible_to(team["researcher"])) == [mine]
    assert Beneficiary.objects.visible_to(team["manager"]).count() == 2
    assert Beneficiary.objects.visible_to(team["fund"]).count() == 0     # fundraising works by case code only
    assert team["fund"].has_perm("cases.view_case_summary")
    for user in (team["researcher"], team["manager"]):                  # research team: no donors or amounts
        assert not user.has_perm("crm.view_donor") and not user.has_perm("crm.view_donation")
        assert not user.has_perm("cases.view_case_funding")
    assert team["projects"].has_perm("cases.view_case_funding")


def test_attachments_follow_record_access(team):
    case = Beneficiary.objects.create(name="حالتي", researcher=team["researcher"])
    bad = SimpleUploadedFile("id.pdf", b"MZ\x90\x00not a pdf")
    assert Attachment.validate_upload(bad)
    good = SimpleUploadedFile("id.pdf", b"%PDF-1.4 test")
    assert Attachment.validate_upload(good) is None
    att = Attachment(record=case, title="البطاقة", file=good, uploaded_by=team["researcher"])
    att.save()
    url = reverse("attachment_download", args=[att.pk])
    c = Client()
    c.force_login(team["researcher"])
    assert c.get(url).status_code == 200
    c.force_login(team["researcher2"])
    assert c.get(url).status_code == 404
    c.force_login(team["manager"])
    assert c.get(url).status_code == 200


def test_login_lockout_and_language(make_user, settings):
    make_user("clerk", "fundraising")
    c = Client()
    for _ in range(settings.MAX_FAILED_LOGINS):
        c.post(reverse("login"), {"username": "clerk", "password": "wrong"})
    r = c.post(reverse("login"), {"username": "clerk", "password": "Str0ng-pass!"})
    assert "مقفل مؤقتاً" in r.content.decode()
    assert AuditLog.objects.filter(action="locked").exists()


def test_bilingual_pages(make_user):
    make_user("clerk", "fundraising")
    c = Client()
    r = c.post(reverse("login"), {"username": "clerk", "password": "Str0ng-pass!"}, follow=True)
    html = r.content.decode()
    assert 'dir="rtl"' in html and "لوحة التحكم" in html
    c.post(reverse("set_language"), {"language": "en", "next": "/"})
    html = c.get("/").content.decode()
    assert 'dir="ltr"' in html and "Dashboard" in html
    from accounts.models import User
    assert User.objects.get(username="clerk").language == "en"


def test_approvals_inbox_page(team):
    case = research_done(Beneficiary.objects.create(name="أسرة الاختبار", researcher=team["researcher"]))
    req = services.submit(case, team["researcher"])
    c = Client()
    c.force_login(team["manager"])
    assert "أسرة الاختبار" in c.get(reverse("approvals_inbox")).content.decode()
    r = c.post(reverse("approval_request", args=[req.pk]), {"decision": "approve"}, follow=True)
    assert r.status_code == 200
    case.refresh_from_db()
    assert case.status == Beneficiary.APPROVED
    c.force_login(team["researcher2"])
    assert c.get(reverse("approval_request", args=[req.pk])).status_code == 404


def test_backoffice_submit_action_and_role_staff_flag(team):
    assert team["researcher"].is_staff  # holding a role opens the back office
    case = research_done(Beneficiary.objects.create(name="أسرة للإرسال", researcher=team["researcher"]))
    other = Beneficiary.objects.create(name="غير مكتملة", researcher=team["researcher"])
    c = Client()
    c.force_login(team["researcher"])
    r = c.post("/backoffice/cases/beneficiary/", {"action": "submit_for_approval",
                                                 "_selected_action": [case.pk, other.pk]}, follow=True)
    html = r.content.decode()
    assert "أكمل البحث أولاً" in html             # the incomplete one is refused with a reason
    case.refresh_from_db(); other.refresh_from_db()
    assert case.status == Beneficiary.RECOMMENDED and other.status == Beneficiary.UNDER_STUDY
    # once submitted, the researcher can no longer edit the case
    assert c.get(f"/backoffice/cases/beneficiary/{case.pk}/change/").status_code in (200, 403)
    page = c.get(f"/backoffice/cases/beneficiary/{case.pk}/change/").content.decode()
    assert 'name="_save"' not in page
    # and cannot see a colleague's case at all
    theirs = Beneficiary.objects.create(name="حالة زميل", researcher=team["researcher2"])
    assert c.get(f"/backoffice/cases/beneficiary/{theirs.pk}/change/", follow=True).status_code in (200, 404)
    assert "حالة زميل" not in c.get("/backoffice/cases/beneficiary/").content.decode()
