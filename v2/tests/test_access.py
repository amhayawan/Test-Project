"""One platform, separate access: each role sees its own modules; management sees all of them.

Runs against the full demo data set, logging in as each demo user.
"""
import io

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import translation

pytestmark = pytest.mark.django_db

GROUPS = {"cases": "Case management", "crm": "Donor management", "hr": "Human resources", "finance": "Finance",
          "supply": "Supply chain", "projects": "Project management"}

# user → menu groups they must see (any group not listed must be hidden)
EXPECTED = {
    "researcher1": {"cases"},
    "casemanager": {"cases", "crm", "supply"},
    "fundraiser": {"cases", "crm"},
    "hrofficer": {"hr"},
    "hrmanager": {"hr", "supply"},
    "payroll": {"hr"},
    "accountant": {"finance", "supply", "projects", "crm"},
    "finmanager": {"finance", "supply", "projects", "crm", "cases"},   # payroll reaches finance as journals, no salaries
    "procurement": {"supply"},
    "storekeeper": {"supply", "cases", "crm"},
    "pm": {"projects", "supply"},
    "director": set(GROUPS),
    "admin": set(GROUPS),
}

# (url, users allowed) — everyone else gets 403 / 404 / redirect
PAGES = [
    ("/finance/trial-balance/", {"accountant", "finmanager", "director", "admin"}),
    ("/finance/balance-sheet/", {"accountant", "finmanager", "director", "admin"}),
    ("/hr/structure/", {"hrofficer", "hrmanager", "payroll", "director", "admin"}),
    ("/projects/", {"pm", "accountant", "finmanager", "director", "admin"}),
    ("/backoffice/hr/payrollrun/", {"payroll", "hrmanager", "director", "admin"}),   # HR manager approves payroll
    ("/backoffice/crm/donor/", {"fundraiser", "casemanager", "finmanager", "director", "admin"}),  # accountant: donations only
]


@pytest.fixture
def demo(settings, tmp_path):
    settings.DATA_DIR = tmp_path
    with translation.override("en"):
        call_command("load_demo", stdout=io.StringIO())


def nav_groups(client):
    from core.context import navigation

    class R:
        path = "/"
    r = R()
    r.user = client.user
    with translation.override("en"):
        return {str(g) for g, _links, _open in navigation(r)["nav_groups"]}


def test_each_role_sees_only_its_modules(demo):
    from accounts.models import User
    for username, expected in EXPECTED.items():
        c = Client()
        c.user = User.objects.get(username=username)
        seen = nav_groups(c)
        want = {GROUPS[k] for k in expected}
        assert want <= seen, (username, "missing", want - seen)
        assert not (seen & {GROUPS[k] for k in set(GROUPS) - expected}), (username, "extra", seen - want)


def test_pages_refuse_other_roles(demo):
    from accounts.models import User
    for url, allowed in PAGES:
        for username in EXPECTED:
            c = Client()
            c.force_login(User.objects.get(username=username))
            code = c.get(url).status_code
            if username in allowed:
                assert code == 200, (url, username, code)
            else:
                assert code in (302, 403, 404), (url, username, code)


def test_management_dashboard_reflects_every_module(demo):
    from accounts.models import User
    c = Client()
    c.force_login(User.objects.get(username="director"))
    with translation.override("en"):
        html = c.get("/?period=this_year", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    for heading in ("Fundraising", "Case management", "Human resources", "Finance", "Project"):
        assert heading in html, heading
    c.force_login(User.objects.get(username="researcher1"))
    html = c.get("/").content.decode()
    assert "Finance" not in html and "Payroll" not in html
