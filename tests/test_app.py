import os
import re
from datetime import date, datetime, timedelta

import pytest

from crm import create_app, storage
from crm.models import Aid, AuditLog, Beneficiary, Donation, Donor, User, db

# Set HAZ_TEST_PG_URL (e.g. postgresql://postgres@localhost:5432/hazcrm_test) to also
# run every test against PostgreSQL. The database is wiped before each test.
PG_URL = os.environ.get("HAZ_TEST_PG_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def app(request, tmp_path):
    config = {"DATA_DIR": str(tmp_path), "TESTING": True}
    if request.param == "postgres":
        if not PG_URL:
            pytest.skip("HAZ_TEST_PG_URL not set")
        config["DATABASE_URL"] = PG_URL
        app = create_app(config)
        with app.app_context():
            db.drop_all()
            db.create_all()
        yield app
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        return
    yield create_app(config)


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def post(client, path, data, form_page=None):
    data = dict(data, _csrf=csrf(client, form_page or path))
    return client.post(path, data=data, follow_redirects=True)


def make_user(app, username="admin", role="admin", password="secret1234"):
    with app.app_context():
        u = User(username=username, name=username, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()


def login(client, username="admin", password="secret1234"):
    return post(client, "/login", {"username": username, "password": password})


@pytest.fixture
def admin(app, client):
    make_user(app)
    login(client)
    return client


def test_first_run_redirects_to_setup_and_creates_admin(client, app):
    assert client.get("/").headers["Location"].endswith("/setup")
    r = post(client, "/setup", {"name": "مدير", "username": "boss",
                                "password": "secret1234", "password2": "secret1234"})
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


def test_short_password_rejected_at_setup(client):
    r = post(client, "/setup", {"name": "x", "username": "x", "password": "short7!", "password2": "short7!"})
    assert "8 أحرف" in r.get_data(as_text=True)


def test_lockout_after_five_failed_logins(app, client):
    make_user(app)
    for _ in range(5):
        login(client, password="wrong")
    r = login(client)  # correct password, but locked
    assert "مقفل مؤقتاً" in r.get_data(as_text=True)
    with app.app_context():
        u = User.query.one()
        assert u.locked_until > datetime.now()
        actions = [a.action for a in AuditLog.query.all()]
        assert actions.count("login_failed") == 5 and "locked" in actions
        u.locked_until = datetime.now() - timedelta(seconds=1)  # lock expires
        db.session.commit()
    assert "لوحة التحكم" in login(client).get_data(as_text=True)


def test_session_expires_and_security_headers(app, admin):
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(minutes=30)
    r = admin.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"
    cookie = admin.get_cookie("session")
    assert cookie.expires is not None and cookie.http_only


def test_audit_log_records_changes(admin, app):
    post(admin, "/donors/new", {"name": "متبرع أ", "donor_type": "individual"})
    with app.app_context():
        did = Donor.query.one().id
    post(admin, f"/donors/{did}/edit", {"name": "متبرع ب", "donor_type": "company"})
    post(admin, f"/donors/{did}/delete", {}, form_page=f"/donors/{did}")
    with app.app_context():
        rows = AuditLog.query.order_by(AuditLog.id).all()
        acts = [(a.action, a.entity) for a in rows if a.entity == "donors"]
        assert acts == [("create", "donors"), ("update", "donors"), ("delete", "donors")]
        update = next(a for a in rows if a.action == "update")
        assert "متبرع أ" in update.summary and "متبرع ب" in update.summary
        assert all(a.username == "admin" for a in rows if a.entity == "donors")
    page = admin.get("/audit/").get_data(as_text=True)
    assert "متبرع ب" in page and "حذف" in page


def test_staff_cannot_see_audit_log(app, client):
    make_user(app)
    make_user(app, "clerk", "staff")
    login(client, "clerk")
    assert client.get("/audit/").status_code == 403


def test_database_url_rules(tmp_path, monkeypatch):
    monkeypatch.delenv("HAZ_CRM_DATABASE_URL", raising=False)
    assert storage.resolve_database_url(tmp_path).startswith("sqlite:///")
    (tmp_path / "settings.ini").write_text("[database]\nurl = postgres://u:p@db.example.com/crm\n")
    url = storage.resolve_database_url(tmp_path)
    assert url.startswith("postgresql+psycopg://u:p@db.example.com/crm") and "sslmode=require" in url
    # local or explicitly configured connections are left alone
    assert "sslmode" not in storage.normalize_url("postgresql://u:p@localhost/crm")
    assert "sslmode=disable" in storage.normalize_url("postgresql://u:p@db/crm?sslmode=disable")
    assert "p@" not in storage.masked(url)
    monkeypatch.setenv("HAZ_CRM_DATABASE_URL", "postgresql://x:y@other.example.com/z")
    assert "other.example.com" in storage.resolve_database_url(tmp_path)


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "crm.db"
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE "user" (id INTEGER PRIMARY KEY, username VARCHAR(64) UNIQUE NOT NULL, '
                'name VARCHAR(120) NOT NULL, password_hash VARCHAR(256) NOT NULL, role VARCHAR(16) NOT NULL, '
                'active BOOLEAN NOT NULL)')
    con.execute("INSERT INTO user VALUES (1, 'old', 'Old', 'x', 'admin', 1)")
    con.commit()
    con.close()
    app = create_app({"DATA_DIR": str(tmp_path)})
    with app.app_context():
        assert User.query.one().failed_logins == 0


def test_auto_backup_keeps_last_n(app, tmp_path):
    make_user(app)
    bdir = tmp_path / "backups"
    with app.app_context():
        first = storage.auto_backup(app.config["DATABASE_URL"], bdir, db.metadata, keep=3)
        assert first and first.read_bytes()[:15] == b"SQLite format 3"
        assert storage.auto_backup(app.config["DATABASE_URL"], bdir, db.metadata, keep=3) is None
        for _ in range(5):
            storage.auto_backup(app.config["DATABASE_URL"], bdir, db.metadata, keep=3,
                                min_age=timedelta(0))
            import time
            time.sleep(1.05)  # file names have 1-second resolution
    assert len(list(bdir.glob("haz-crm-*.db"))) == 3


def test_migrate_sqlite_to_another_database(admin, app, tmp_path):
    if not storage.is_sqlite(app.config["DATABASE_URL"]):
        pytest.skip("source must be the local file")
    post(admin, "/donors/new", {"name": "منقول", "donor_type": "individual"})
    with app.app_context():
        did = Donor.query.one().id
    post(admin, "/donations/new", {"donor_id": did, "amount": "100", "method": "cash",
                                   "purpose": "general", "donation_date": "2026-05-01"})
    target = PG_URL or f"sqlite:///{tmp_path / 'target.db'}"
    if PG_URL:
        tgt_app = create_app({"DATA_DIR": str(tmp_path / "t"), "DATABASE_URL": PG_URL})
        with tgt_app.app_context():
            db.drop_all()
            db.engine.dispose()
    counts = storage.copy_database(app.config["DATABASE_URL"], storage.normalize_url(target), db.metadata)
    assert counts["donor"] == 1 and counts["donation"] == 1 and counts["user"] == 1
    with pytest.raises(RuntimeError):  # refuses to copy into a database that has data
        storage.copy_database(app.config["DATABASE_URL"], storage.normalize_url(target), db.metadata)
    new = create_app({"DATA_DIR": str(tmp_path / "n"), "DATABASE_URL": target})
    c = new.test_client()
    login(c)
    assert "منقول" in c.get(f"/donors/{did}").get_data(as_text=True)
    # IDs keep counting after the copied rows (PostgreSQL sequences were reset)
    post(c, "/donors/new", {"name": "جديد", "donor_type": "individual"})
    with new.app_context():
        assert Donor.query.count() == 2


def test_demo_data_loads_once_and_renders(app, client):
    from crm.demo import load_demo_data
    with app.app_context():
        counts = load_demo_data(today=date(2026, 10, 18))
        assert counts["donations"] > 100 and counts["beneficiaries"] == 46
        assert len({b.national_id for b in Beneficiary.query.all()}) == 46
        with pytest.raises(RuntimeError):
            load_demo_data()
    login(client, "admin", "demo1234")
    for path in ("/", "/donors/", "/beneficiaries/", "/donations/", "/aids/", "/members/", "/volunteers/"):
        assert client.get(path).status_code == 200


def test_long_pickers_are_searchable(admin):
    page = admin.get("/donations/new").get_data(as_text=True)
    assert page.count("data-search") == 4  # donor, case, need, sponsorship
    assert "picker.js" in page
    js = admin.get("/static/picker.js")
    assert js.status_code == 200 and b"normalize" in js.data
