import io
from datetime import date, timedelta

import pytest

from crm.models import (Beneficiary, CaseDocument, CaseNeed, Donation, Donor, FamilyMember, Sponsorship, User,
                        db)
from test_app import app, client, csrf, login, make_user, post  # noqa: F401  (pytest fixtures + helpers)

PDF = b"%PDF-1.4\n%fake test pdf\n"


@pytest.fixture
def team(app):
    make_user(app)                                   # admin
    make_user(app, "manager", "case_manager")
    make_user(app, "res1", "researcher")
    make_user(app, "res2", "researcher")
    make_user(app, "clerk", "staff")
    return app


def as_user(app, username):
    c = app.test_client()
    login(c, username)
    return c


def new_case(c, app, name="أسرة اختبار", nid="29001011234567", **extra):
    data = {"name": name, "national_id": nid, "category": "poor_family", "status": "under_study"}
    data.update(extra)
    post(c, "/beneficiaries/new", data)
    with app.app_context():
        return Beneficiary.query.filter_by(national_id=nid).one().id


def complete_research(c, case_id, zakat="yes"):
    return post(c, f"/cases/{case_id}/research", {
        "visit_date": date.today().isoformat(), "zakat_eligible": zakat, "housing_type": "rent_old",
        "housing_condition": "poor", "research_findings": "زيارة ميدانية، الأسرة بلا دخل ثابت",
        "recommendation": "قبول — إعانة شهرية"}, form_page=f"/cases/{case_id}/research")


def approve(app, case_id):
    m = as_user(app, "manager")
    return post(m, f"/cases/{case_id}/review", {"decision": "approve"}, form_page=f"/cases/{case_id}")


def test_researcher_sees_only_own_cases_and_no_money(team):
    app = team
    r1, r2 = as_user(app, "res1"), as_user(app, "res2")
    case_id = new_case(r1, app)
    with app.app_context():
        assert db.session.get(Beneficiary, case_id).researcher.username == "res1"
    assert r1.get(f"/cases/{case_id}").status_code == 200
    assert r2.get(f"/cases/{case_id}").status_code == 403
    assert "أسرة اختبار" not in r2.get("/beneficiaries/").get_data(as_text=True)
    for path in ("/donors/", "/donations/", "/sponsorships/", "/needs/", "/aids/", "/users/", "/audit/"):
        assert r1.get(path).status_code == 403, path
    assert r1.get("/").headers["Location"].endswith("/cases/")
    page = r1.get(f"/cases/{case_id}").get_data(as_text=True)
    assert "التمويل والكفالات" not in page


def test_workflow_research_submit_review(team):
    app = team
    r1 = as_user(app, "res1")
    case_id = new_case(r1, app)
    # researcher cannot self-approve through the edit form
    r = post(r1, f"/beneficiaries/{case_id}/edit", {"name": "أسرة اختبار", "national_id": "29001011234567",
                                                    "category": "poor_family", "status": "approved"},
             form_page=f"/beneficiaries/{case_id}/edit")
    assert "من صلاحية مدير إدارة الحالات" in r.get_data(as_text=True)
    # cannot submit before research is complete
    r = post(r1, f"/cases/{case_id}/submit", {}, form_page=f"/cases/{case_id}")
    assert "أكمل البحث أولاً" in r.get_data(as_text=True)
    complete_research(r1, case_id)
    post(r1, f"/cases/{case_id}/submit", {}, form_page=f"/cases/{case_id}")
    with app.app_context():
        assert db.session.get(Beneficiary, case_id).status == "recommended"
    # locked for the researcher once submitted
    r = r1.get(f"/cases/{case_id}/research", follow_redirects=True)
    assert "لا يمكن تعديل هذه الحالة الآن" in r.get_data(as_text=True)
    # researchers cannot review
    assert r1.post(f"/cases/{case_id}/review", data={"_csrf": csrf(r1, f"/cases/{case_id}"),
                                                     "decision": "approve"}).status_code == 403
    m = as_user(app, "manager")
    r = post(m, f"/cases/{case_id}/review", {"decision": "return"}, form_page=f"/cases/{case_id}")
    assert "اكتب سبب القرار" in r.get_data(as_text=True)
    post(m, f"/cases/{case_id}/review", {"decision": "return", "review_note": "ينقص صورة البطاقة"},
         form_page=f"/cases/{case_id}")
    with app.app_context():
        assert db.session.get(Beneficiary, case_id).status == "under_study"
    post(r1, f"/cases/{case_id}/submit", {}, form_page=f"/cases/{case_id}")
    approve(app, case_id)
    with app.app_context():
        case = db.session.get(Beneficiary, case_id)
        assert case.status == "approved" and case.reviewed_by.username == "manager"
    hist = m.get(f"/cases/{case_id}").get_data(as_text=True)
    for word in ("إرسال للاعتماد", "إعادة للبحث", "اعتماد حالة", "تحديث البحث الاجتماعي"):
        assert word in hist


def test_manager_assigns_unassigned_case(team):
    app = team
    clerk = as_user(app, "clerk")
    case_id = new_case(clerk, app)
    with app.app_context():
        assert db.session.get(Beneficiary, case_id).researcher_id is None
        res2 = User.query.filter_by(username="res2").one().id
    assert "غير مسندة" in clerk.get("/cases/?stage=unassigned").get_data(as_text=True)
    m = as_user(app, "manager")
    post(m, f"/cases/{case_id}/assign", {"researcher_id": res2}, form_page=f"/cases/{case_id}")
    with app.app_context():
        assert db.session.get(Beneficiary, case_id).researcher_id == res2
    assert as_user(app, "res2").get(f"/cases/{case_id}").status_code == 200
    # staff cannot assign
    assert clerk.post(f"/cases/{case_id}/assign", data={"_csrf": csrf(clerk, f"/cases/{case_id}"),
                                                        "researcher_id": res2}).status_code == 403


def test_family_and_needs(team):
    app = team
    r1 = as_user(app, "res1")
    case_id = new_case(r1, app)
    for name, rel in (("الأب", "head"), ("الابن", "son"), ("الابنة", "daughter")):
        post(r1, f"/cases/{case_id}/family", {"name": name, "relation": rel, "birth_year": "2012"},
             form_page=f"/cases/{case_id}")
    post(r1, f"/cases/{case_id}/needs", {"need_type": "medical", "description": "عملية للابن",
                                         "amount_needed": "15000", "priority": "urgent", "frequency": "once"},
         form_page=f"/cases/{case_id}")
    r = post(r1, f"/cases/{case_id}/needs", {"need_type": "food", "description": "", "amount_needed": "0"},
             form_page=f"/cases/{case_id}")
    assert "وصف الاحتياج مطلوب" in r.get_data(as_text=True)
    with app.app_context():
        case = db.session.get(Beneficiary, case_id)
        assert case.family_size == 3 and len(case.family) == 3
        assert [n.description for n in case.needs] == ["عملية للابن"]
        assert case.needs[0].funding_state == "open"


def funded_case(app, zakat="yes"):
    r1 = as_user(app, "res1")
    case_id = new_case(r1, app, nid=f"2900101{zakat == 'yes' and '1' or '2'}234567")
    post(r1, f"/cases/{case_id}/needs", {"need_type": "medical", "description": "عملية",
                                         "amount_needed": "10000", "priority": "urgent", "frequency": "once"},
         form_page=f"/cases/{case_id}")
    complete_research(r1, case_id, zakat=zakat)
    post(r1, f"/cases/{case_id}/submit", {}, form_page=f"/cases/{case_id}")
    with app.app_context():
        donor = Donor(name="متبرع", donor_type="individual")
        other = Donor(name="متبرع آخر", donor_type="individual")
        db.session.add_all([donor, other])
        db.session.commit()
        return case_id, donor.id, other.id, CaseNeed.query.filter_by(beneficiary_id=case_id).one().id


def donate(c, donor_id, amount, purpose="general", **extra):
    data = {"donor_id": donor_id, "amount": amount, "method": "cash", "purpose": purpose,
            "donation_date": date.today().isoformat()}
    data.update(extra)
    return post(c, "/donations/new", data)


def test_earmarked_donations_fund_needs(team):
    app = team
    case_id, donor_id, _, need_id = funded_case(app)
    clerk = as_user(app, "clerk")
    r = donate(clerk, donor_id, "4000", beneficiary_id=case_id)
    assert "لا يمكن التخصيص إلا لحالة معتمدة" in r.get_data(as_text=True)
    approve(app, case_id)
    donate(clerk, donor_id, "4000", need_id=need_id)          # case filled in from the need
    with app.app_context():
        need = db.session.get(CaseNeed, need_id)
        assert need.funding_state == "partial" and float(need.funded) == 4000
        assert Donation.query.one().beneficiary_id == case_id
    donate(clerk, donor_id, "6000", purpose="zakat", need_id=need_id)
    with app.app_context():
        assert db.session.get(CaseNeed, need_id).funding_state == "funded"
    page = clerk.get(f"/cases/{case_id}").get_data(as_text=True)
    assert "تبرعات مخصصة لهذه الحالة" in page and "متبرع" in page
    # researchers see progress but not who paid
    r_page = as_user(app, "res1").get(f"/cases/{case_id}").get_data(as_text=True)
    assert "ممول بالكامل" in r_page
    assert "متبرع" not in r_page.replace("المتبرعون", "")
    assert "تبرعات مخصصة لهذه الحالة" not in r_page and "التمويل والكفالات" not in r_page


def test_zakat_only_to_eligible_cases(team):
    app = team
    case_id, donor_id, _, _ = funded_case(app, zakat="no")
    approve(app, case_id)
    clerk = as_user(app, "clerk")
    r = donate(clerk, donor_id, "500", purpose="zakat", beneficiary_id=case_id)
    assert "غير مستحقة للزكاة" in r.get_data(as_text=True)
    donate(clerk, donor_id, "500", purpose="sadaqa", beneficiary_id=case_id)
    with app.app_context():
        assert Donation.query.count() == 1


def test_sponsorship_payments_and_arrears(team):
    app = team
    case_id, donor_id, other_id, _ = funded_case(app)
    approve(app, case_id)
    clerk = as_user(app, "clerk")
    start = (date.today().replace(day=1) - timedelta(days=40)).replace(day=1)   # two months ago
    post(clerk, "/sponsorships/new", {"donor_id": donor_id, "beneficiary_id": case_id, "monthly_amount": "1000",
                                      "start_date": start.isoformat(), "status": "active"})
    with app.app_context():
        s = Sponsorship.query.one()
        sid = s.id
        assert s.months_due() == 3 and float(s.arrears) == 3000
    r = donate(clerk, other_id, "1000", purpose="orphans", sponsorship_id=sid)
    assert "باسم متبرع آخر" in r.get_data(as_text=True)
    donate(clerk, donor_id, "1000", purpose="orphans", sponsorship_id=sid)
    with app.app_context():
        s = db.session.get(Sponsorship, sid)
        assert float(s.arrears) == 2000 and s.paid_this_month
        assert Donation.query.one().beneficiary_id == case_id
    assert "كفالات لم تُسدَّد" in clerk.get("/cases/").get_data(as_text=True)


def test_documents_upload_download_and_access(team):
    app = team
    r1 = as_user(app, "res1")
    case_id = new_case(r1, app)
    tok = csrf(r1, f"/cases/{case_id}")
    r = r1.post(f"/cases/{case_id}/documents", data={"_csrf": tok, "title": "البطاقة",
                                                    "file": (io.BytesIO(PDF), "id.pdf")},
                content_type="multipart/form-data", follow_redirects=True)
    assert "تم رفع المستند" in r.get_data(as_text=True)
    r = r1.post(f"/cases/{case_id}/documents", data={"_csrf": tok, "title": "x",
                                                    "file": (io.BytesIO(b"MZ\x90\x00evil"), "virus.pdf")},
                content_type="multipart/form-data", follow_redirects=True)
    assert "الملفات المسموحة" in r.get_data(as_text=True)
    with app.app_context():
        doc = CaseDocument.query.one()
        assert doc.title == "البطاقة"
    got = r1.get(f"/cases/{case_id}/documents/{doc.id}")
    assert got.status_code == 200 and got.data == PDF
    assert as_user(app, "res2").get(f"/cases/{case_id}/documents/{doc.id}").status_code == 403
    assert as_user(app, "manager").get(f"/cases/{case_id}/documents/{doc.id}").status_code == 200


def test_case_with_needs_cannot_be_deleted(team):
    app = team
    r1 = as_user(app, "res1")
    case_id = new_case(r1, app)
    post(r1, f"/cases/{case_id}/needs", {"need_type": "food", "description": "غذاء", "amount_needed": "500"},
         form_page=f"/cases/{case_id}")
    admin = as_user(app, "admin")
    r = post(admin, f"/beneficiaries/{case_id}/delete", {}, form_page=f"/cases/{case_id}")
    assert "لا يمكن الحذف" in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Beneficiary, case_id) is not None


def test_role_change_by_admin(team):
    app = team
    admin = as_user(app, "admin")
    with app.app_context():
        uid = User.query.filter_by(username="clerk").one().id
    post(admin, f"/users/{uid}/role", {"role": "researcher"}, form_page="/users/")
    with app.app_context():
        assert db.session.get(User, uid).role == "researcher"


def test_old_database_gets_case_columns(tmp_path):
    import sqlite3
    from crm import create_app
    path = tmp_path / "crm.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE beneficiary (id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, national_id VARCHAR(14), "
                "phone VARCHAR(30), address VARCHAR(255), area VARCHAR(80), category VARCHAR(20) NOT NULL, "
                "family_size INTEGER, monthly_income NUMERIC(12,2), status VARCHAR(20) NOT NULL, notes TEXT, "
                "created_at DATETIME NOT NULL)")
    con.execute("INSERT INTO beneficiary VALUES (1, 'قديمة', NULL, NULL, NULL, NULL, 'orphan', 2, 0, 'approved', NULL, "
                "'2026-01-01 00:00:00')")
    con.commit()
    con.close()
    app = create_app({"DATA_DIR": str(tmp_path)})
    with app.app_context():
        case = db.session.get(Beneficiary, 1)
        assert case.researcher_id is None and case.zakat_eligible is None and case.stage == "approved"
        assert FamilyMember.query.count() == 0


def test_monthly_need_counts_current_month_only(team):
    app = team
    case_id, donor_id, _, _ = funded_case(app)
    approve(app, case_id)
    with app.app_context():
        need = CaseNeed(beneficiary_id=case_id, need_type="monthly", description="إعانة شهرية",
                        amount_needed=1000, frequency="monthly")
        db.session.add(need)
        db.session.commit()
        need_id = need.id
    clerk = as_user(app, "clerk")
    last_month = date.today().replace(day=1) - timedelta(days=1)
    donate(clerk, donor_id, "1000", need_id=need_id, donation_date=last_month.isoformat())
    with app.app_context():
        need = db.session.get(CaseNeed, need_id)
        assert need.funding_state == "open" and float(need.funded_total) == 1000
    donate(clerk, donor_id, "1000", need_id=need_id)
    with app.app_context():
        assert db.session.get(CaseNeed, need_id).funding_state == "funded"
