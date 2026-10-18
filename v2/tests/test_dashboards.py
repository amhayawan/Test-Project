from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from cases.models import Aid, Beneficiary
from crm.models import Campaign, Donation, Donor
from dashboards import filters as flt
from dashboards.widgets import build

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 18)


def test_period_presets_and_buckets():
    f = flt.parse({"period": "last_month"}, today=TODAY)
    assert (f.start, f.end) == (date(2026, 9, 1), date(2026, 9, 30)) and f.granularity == "day"
    assert f.previous == (date(2026, 8, 2), date(2026, 8, 31))
    f = flt.parse({"period": "this_quarter"}, today=TODAY)
    assert f.start == date(2026, 10, 1)
    f = flt.parse({"period": "last_90"}, today=TODAY)
    assert f.granularity == "week" and f.buckets()[-1][2] == TODAY
    f = flt.parse({"period": "this_year"}, today=TODAY)
    assert f.granularity == "month" and len(f.buckets()) == 10
    f = flt.parse({"period": "custom", "from": "2026-03-31", "to": "2026-01-01"}, today=TODAY)
    assert (f.start, f.end) == (date(2026, 1, 1), date(2026, 3, 31))      # swapped automatically
    f = flt.parse({"period": "custom", "from": "rubbish"}, today=TODAY)
    assert f.errors and f.preset == flt.DEFAULT_PRESET
    assert flt.parse({"period": "nonsense"}, today=TODAY).preset == flt.DEFAULT_PRESET


@pytest.fixture
def people(make_user):
    return {r: make_user(r, r) for r in ("admin", "executive", "case_manager", "researcher", "fundraising")}


def test_each_role_gets_its_own_dashboard(people):
    f = flt.parse({"period": "this_year"})
    seen = {role: {k for k, v in build(user, f).items() if v} for role, user in people.items()}
    assert seen["researcher"] == {"approvals", "my_cases"}                       # no money at all
    assert "fundraising" in seen["fundraising"] and "administration" not in seen["fundraising"]
    # Research Department manager: cases and the aid given, but no donors, donations or sponsorship money
    assert {"case_management", "aid"} <= seen["case_manager"]
    assert not {"administration", "fundraising", "overview", "sponsorships"} & seen["case_manager"]
    assert {"overview", "case_management", "fundraising", "administration"} <= seen["executive"]
    assert "administration" in seen["admin"]
    c = Client()
    for role, user in people.items():
        c.force_login(user)
        html = c.get("/?period=last_month").content.decode()
        assert ("المتبرعين" in html or "التبرعات" in html) == bool({"fundraising", "overview"} & seen[role])


def test_filters_change_the_numbers(people):
    donor = Donor.objects.create(name="متبرع")
    camp = Campaign.objects.create(code="RAM", name="رمضان", start_date=date(2026, 2, 1), target=Decimal("1000"))
    today = date.today()
    Donation.objects.create(donor=donor, amount=Decimal("100"), donation_date=today)
    Donation.objects.create(donor=donor, amount=Decimal("300"), donation_date=today, campaign=camp)
    Donation.objects.create(donor=donor, amount=Decimal("50"), donation_date=today - timedelta(days=200))
    user = people["fundraising"]
    total = lambda **p: build(user, flt.parse(p))["fundraising"]["kpis"][0]["value"]
    assert total(period="last_30") == Decimal("400")
    assert total(period="last_30", campaign=str(camp.pk)) == Decimal("300")
    start = (today - timedelta(days=400)).isoformat()
    assert total(period="custom", **{"from": start, "to": today.isoformat()}) == Decimal("450")
    camp_row = build(user, flt.parse({"period": "last_30"}))["fundraising"]["campaigns"][0]
    assert camp_row["pct"] == 30.0


def test_researcher_dashboard_lists_returned_and_missing(people, make_user):
    from approvals import services
    from django.utils import timezone
    res = people["researcher"]
    case = Beneficiary.objects.create(name="أسرة", researcher=res, visit_date=timezone.localdate(),
                                      zakat_eligible="yes", research_findings="x", recommendation="y",
                                      assessment="urgent")
    Beneficiary.objects.create(name="ناقصة", researcher=res)
    req = services.submit(case, res)
    services.decide(req, people["case_manager"], "return", "صورة البطاقة")
    s = build(res, flt.parse({}))["my_cases"]
    assert s["kpis"][1]["value"] == 1                       # returned to me
    missing = [t for t in s["todo"] if t["missing"]]
    assert len(missing) == 1


def test_access_matrix_and_segregation_of_duties(people, make_user):
    risky = make_user("risky", "researcher", "case_manager")
    c = Client()
    c.force_login(people["researcher"])
    assert c.get("/access/").status_code == 403
    c.force_login(people["executive"])
    html = c.get("/access/").content.decode()
    assert "الفصل بين المهام" in html and risky.display_name in html
    from accounts.sod import conflicts
    assert any(x["user"] == risky for x in conflicts())
    assert not any(x["user"] == people["researcher"] for x in conflicts())
