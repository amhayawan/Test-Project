"""The association's process: research form → Research Dept manager → Projects Dept → aid; donors use case codes;
the research team sees only whether a need's amount is collected."""
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import translation

from approvals import services
from cases.models import Aid, Beneficiary, CaseNeed, HouseholdItem, MedicalCondition
from crm.admin import DonationForm
from crm.models import Donation, Donor

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


@pytest.fixture
def team(make_user):
    return {"researcher": make_user("res", "researcher", staff=True), "rm": make_user("rm", "case_manager", staff=True),
            "projects": make_user("proj", "projects_officer", staff=True),
            "pm": make_user("pm", "project_manager", staff=True), "fund": make_user("fund", "fundraising", staff=True)}


def researched(team):
    c = Beneficiary.objects.create(name="فاطمة محمود", national_id="28001011234567", phone="01000000000",
                                   researcher=team["researcher"], visit_date=date(2026, 3, 1), zakat_eligible="yes",
                                   research_findings="أسرة بلا دخل ثابت", recommendation="قبول", assessment="urgent",
                                   marital_status="widow", income_takaful=D(750), income_benefactors=D(250),
                                   exp_food_daily=D(80), exp_rent=D(600), exp_electricity=D(150))
    MedicalCondition.objects.create(beneficiary=c, patient="ابن", illness="ربو", treatment_cost=D(300))
    return c


def test_research_form_totals_and_checklist(team):
    c = researched(team)
    assert c.total_income == D(1000) and c.monthly_income == D(1000)
    assert c.total_expenses == D(80 * 30 + 600 + 150) and c.monthly_gap == D(2150)
    assert c.household.count() == len(HouseholdItem.ITEMS)
    cl = Client()
    cl.force_login(team["researcher"])
    page = cl.get(f"/cases/{c.pk}/research-form/").content.decode()
    assert "استمارة بحث ميداني" in page and "وصف دقيق لحالة المسكن" in page and "فاطمة محمود" in page
    assert cl.get("/cases/research-form/blank/").status_code == 200
    assert cl.get(f"/backoffice/cases/beneficiary/{c.pk}/change/").status_code == 200
    cl.force_login(team["fund"])
    assert cl.get(f"/cases/{c.pk}/research-form/").status_code == 404     # fundraising never sees the file


def test_research_manager_accepts_and_projects_department_gives_aid(team):
    c = researched(team)
    incomplete = Beneficiary.objects.create(name="x", researcher=team["researcher"])
    with pytest.raises(Exception):
        services.submit(incomplete, team["researcher"])                 # research form not complete
    req = services.submit(c, team["researcher"])
    assert not services.can_act(req, team["projects"]) and services.can_act(req, team["rm"])
    services.decide(req, team["rm"], "approve")
    c.refresh_from_db()
    assert c.status == Beneficiary.APPROVED and c.referred_at is not None        # referred to Projects
    assert not team["rm"].has_perm("cases.add_aid") and team["projects"].has_perm("cases.add_aid")
    aid = Aid.objects.create(beneficiary=c, value=D(1500), requested_by=team["projects"])
    req = services.submit(aid, team["projects"])
    assert not services.can_act(req, team["rm"])
    services.decide(req, team["pm"], "approve")
    aid.refresh_from_db()
    assert aid.status == Aid.APPROVED


def test_donors_use_the_case_code_and_researchers_only_see_collected_or_not(team):
    c = researched(team)
    services.decide(services.submit(c, team["researcher"]), team["rm"], "approve")
    c.refresh_from_db()
    need = CaseNeed.objects.create(beneficiary=c, need_type="medical", description="علاج", amount_needed=D(2000))
    donor = Donor.objects.create(name="متبرع")
    form = DonationForm(data={"donor": donor.pk, "amount": "500", "method": "cash", "purpose": "medical",
                              "donation_date": "2026-03-05", "case_code": "C-1999-99999"})
    assert not form.is_valid() and "case_code" in form.errors
    form = DonationForm(data={"donor": donor.pk, "amount": "500", "method": "cash", "purpose": "medical",
                              "donation_date": "2026-03-05", "case_code": c.case_no.lower(), "need": need.pk})
    assert form.is_valid(), form.errors
    d = form.save()
    assert d.beneficiary == c and need.funding_label == "Partly collected"

    cl = Client()
    cl.force_login(team["fund"])
    page = cl.get("/cases/available/").content.decode()
    assert c.case_no in page and "فاطمة" not in page and "28001011234567" not in page and "01000000000" not in page
    add = cl.get("/backoffice/crm/donation/add/").content.decode()
    assert "فاطمة" not in add                                                  # needs listed by code, not name

    cl.force_login(team["researcher"])
    change = cl.get(f"/backoffice/cases/beneficiary/{c.pk}/change/").content.decode()
    assert "تم تجميع جزء من المبلغ" in change and "متبرع" not in change and "R-20" not in change
    assert cl.get("/backoffice/crm/donation/").status_code == 403
    Donation.objects.create(donor=donor, amount=D(1500), need=need, beneficiary=c, donation_date=date(2026, 3, 6))
    assert need.funding_state == "funded"
