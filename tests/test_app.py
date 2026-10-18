import re
from datetime import date

import pytest

from crm import create_app
from crm.models import Aid, Beneficiary, Donation, Donor, User, db


@pytest.fixture
def app(tmp_path):
    return create_app({"DATA_DIR": str(tmp_path), "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def post(client, path, data, form_page=None):
    data = dict(data, _csrf=csrf(client, form_page or path))
    return client.post(path, data=data, follow_redirects=True)


def make_user(app, username="admin", role="admin", password="secret123"):
    with app.app_context():
        u = User(username=username, name=username, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()


def login(client, username="admin", password="secret123"):
    return post(client, "/login", {"username": username, "password": password})


@pytest.fixture
def admin(app, client):
    make_user(app)
    login(client)
    return client


def test_first_run_redirects_to_setup_and_creates_admin(client, app):
    assert client.get("/").headers["Location"].endswith("/setup")
    r = post(client, "/setup", {"name": "مدير", "username": "boss",
                                "password": "secret123", "password2": "secret123"})
    assert "لوحة التحكم" in r.get_data(as_text=True)
    with app.app_context():
        assert User.query.one().role == "admin"
    # setup is locked once an account exists
    assert client.get("/setup").status_code == 302


def test_login_required_and_bad_password(app, client):
    make_user(app)
    assert "/login" in client.get("/donors/").headers["Location"]
    r = login(client, password="wrong")
    assert "غير صحيحة" in r.get_data(as_text=True)


def test_post_without_csrf_rejected(admin):
    assert admin.post("/donors/new", data={"name": "x", "donor_type": "individual"}).status_code == 400


def test_donor_donation_flow_and_receipt_numbers(admin, app):
    r = post(admin, "/donors/new", {"name": "أحمد علي", "donor_type": "individual", "phone": "01001234567"})
    assert "تم حفظ" in r.get_data(as_text=True)
    with app.app_context():
        donor_id = Donor.query.one().id
    for amount in ("500", "1,250.50"):
        post(admin, "/donations/new", {"donor_id": donor_id, "amount": amount, "method": "cash",
                                       "purpose": "zakat", "donation_date": "2026-03-01"})
    with app.app_context():
        nos = sorted(d.receipt_no for d in Donation.query.all())
        assert nos == ["R-2026-00001", "R-2026-00002"]
        assert float(db.session.get(Donor, donor_id).total_donated) == 1750.50
        did = Donation.query.first().id
    page = admin.get(f"/donors/{donor_id}").get_data(as_text=True)
    assert "1,750.50" in page
    receipt = admin.get(f"/donations/{did}/receipt").get_data(as_text=True)
    assert "أحمد علي" in receipt and "زكاة مال" in receipt


def test_validation_errors(admin):
    r = post(admin, "/beneficiaries/new", {"name": "", "national_id": "123", "category": "orphan",
                                           "status": "approved", "phone": "abc"})
    html = r.get_data(as_text=True)
    assert "الاسم مطلوب" in html
    assert "14 رقماً" in html
    assert "رقم هاتف غير صحيح" in html
    r = post(admin, "/donations/new", {"amount": "0", "method": "cash", "purpose": "general",
                                       "donation_date": "2026-01-01"})
    assert "أكبر من صفر" in r.get_data(as_text=True)


def test_duplicate_national_id_blocked(admin, app):
    data = {"name": "سعاد", "national_id": "29001011234567", "category": "widow", "status": "approved"}
    post(admin, "/beneficiaries/new", data)
    r = post(admin, "/beneficiaries/new", dict(data, name="أخرى"))
    assert "مكرر" in r.get_data(as_text=True)
    with app.app_context():
        assert Beneficiary.query.count() == 1


def test_aid_and_delete_protection(admin, app):
    post(admin, "/beneficiaries/new", {"name": "أسرة", "category": "poor_family", "status": "approved"})
    with app.app_context():
        bid = Beneficiary.query.one().id
    post(admin, "/aids/new", {"beneficiary_id": bid, "aid_type": "food", "value": "300",
                              "aid_date": date.today().isoformat()})
    r = post(admin, f"/beneficiaries/{bid}/delete", {}, form_page=f"/beneficiaries/{bid}")
    assert "لا يمكن الحذف" in r.get_data(as_text=True)
    with app.app_context():
        assert Aid.query.count() == 1
    dash = admin.get("/").get_data(as_text=True)
    assert "300.00" in dash


def test_staff_cannot_delete_or_manage_users(app, client):
    make_user(app)
    make_user(app, "clerk", "staff")
    login(client, "clerk")
    post(client, "/donors/new", {"name": "متبرع", "donor_type": "company"})
    with app.app_context():
        did = Donor.query.one().id
    token = csrf(client, f"/donors/{did}")
    assert client.post(f"/donors/{did}/delete", data={"_csrf": token}).status_code == 403
    assert client.get("/users/").status_code == 403
    assert client.get("/backup").status_code == 403


def test_edit_search_export_and_backup(admin, app):
    post(admin, "/donors/new", {"name": "شركة النور", "donor_type": "company"})
    with app.app_context():
        did = Donor.query.one().id
    post(admin, f"/donors/{did}/edit", {"name": "شركة النور للتجارة", "donor_type": "company"})
    assert "شركة النور للتجارة" in admin.get("/donors/?q=النور").get_data(as_text=True)
    assert "لا توجد سجلات" in admin.get("/donors/?q=zzz").get_data(as_text=True)
    csv_text = admin.get("/donors/export.csv").get_data(as_text=True)
    assert csv_text.startswith("﻿") and "شركة / مؤسسة" in csv_text
    backup = admin.get("/backup")
    assert backup.status_code == 200 and backup.data[:15] == b"SQLite format 3"


def test_all_list_and_new_pages_render(admin):
    for name in ("donors", "donations", "beneficiaries", "aids", "volunteers", "members"):
        assert admin.get(f"/{name}/").status_code == 200
        assert admin.get(f"/{name}/new").status_code == 200
    assert admin.get("/nope/").status_code == 404
