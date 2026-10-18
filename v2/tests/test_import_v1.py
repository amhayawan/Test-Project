"""Import a real v1 database (built by running the v1 app with its demo data)."""
import io
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib.auth import authenticate
from django.core.management import call_command

from accounts.models import User
from approvals import services
from cases.models import Aid, Beneficiary, CaseNeed, FamilyMember
from core.models import Attachment
from crm.models import Donation, Donor, Member, Sponsorship, Volunteer

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module")
def v1_db(tmp_path_factory):
    data = tmp_path_factory.mktemp("v1")
    try:
        subprocess.run([sys.executable, str(REPO / "haz_crm.py"), "--data", str(data), "--load-demo"],
                       cwd=REPO, check=True, capture_output=True, timeout=180)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        pytest.skip(f"v1 app not runnable here: {exc}")
    db = data / "crm.db"
    # add one case document the way v1 stores them
    con = sqlite3.connect(db)
    case_id = con.execute("select id from beneficiary limit 1").fetchone()[0]
    (data / "uploads" / str(case_id)).mkdir(parents=True)
    (data / "uploads" / str(case_id) / "abc123.pdf").write_bytes(b"%PDF-1.4 v1 document")
    con.execute("insert into case_document (beneficiary_id, title, stored_name, original_name, content_type, size, "
                "created_at) values (?, 'صورة البطاقة', 'abc123.pdf', 'id.pdf', 'application/pdf', 20, "
                "'2026-05-01 10:00:00')", (case_id,))
    con.commit()
    counts = {t: con.execute(f'select count(*) from "{t}"').fetchone()[0]
              for t in ("user", "donor", "donation", "beneficiary", "aid", "case_need", "sponsorship",
                        "family_member", "volunteer", "member")}
    con.close()
    return db, counts


def test_import_everything_from_v1(seeded, v1_db):
    db, counts = v1_db
    out = io.StringIO()
    call_command("import_v1", str(db), stdout=out)
    assert User.objects.count() == counts["user"]
    assert Donor.objects.count() == counts["donor"]
    assert Donation.objects.count() == counts["donation"]
    assert Beneficiary.objects.count() == counts["beneficiary"]
    assert Aid.objects.filter(status=Aid.DELIVERED).count() == counts["aid"]
    assert CaseNeed.objects.count() == counts["case_need"]
    assert Sponsorship.objects.count() == counts["sponsorship"]
    assert FamilyMember.objects.count() == counts["family_member"]
    assert Volunteer.objects.count() == counts["volunteer"]
    assert Member.objects.count() == counts["member"]
    assert Attachment.objects.count() == 1 and Attachment.objects.get().file.read() == b"%PDF-1.4 v1 document"

    # links survive: sponsorship payments point at the sponsorship and its case
    s = Sponsorship.objects.first()
    assert s.payments.exists() and all(p.beneficiary_id == s.beneficiary_id for p in s.payments.all())
    # numbering continues after the imported receipts
    last = max(Donation.objects.values_list("receipt_no", flat=True))
    new = Donation.objects.create(donor=Donor.objects.first(), amount=10, donation_date=f"{last[2:6]}-12-31")
    assert int(new.receipt_no[-5:]) == int(last[-5:]) + 1

    # staff keep their v1 password; the hash is upgraded on first login
    user = authenticate(username="researcher", password="demo1234")
    assert user is not None and user.has_role("researcher")
    assert not User.objects.get(username="researcher").password.startswith("wz$")
    assert all(len(u.password) <= 128 for u in User.objects.all())
    assert authenticate(username="researcher", password="wrong") is None
    assert User.objects.get(username="admin").has_role("admin")

    # imported researchers see only their own cases
    assert 0 < Beneficiary.objects.visible_to(user).count() < Beneficiary.objects.count()

    # cases that were awaiting approval in v1 are in a manager's approval inbox
    recommended = Beneficiary.objects.filter(status=Beneficiary.RECOMMENDED)
    manager = User.objects.get(username="manager")
    assert recommended.exists() and len(services.inbox(manager)) == recommended.count()
    req = services.inbox(manager)[0]
    services.decide(req, manager, "approve")
    assert Beneficiary.objects.get(pk=req.object_id).status == Beneficiary.APPROVED

    # the approval engine works on imported data
    waiting = Beneficiary.objects.filter(status=Beneficiary.UNDER_STUDY, researcher=user).first()
    if waiting and not waiting.research_missing:
        services.submit(waiting, user)

    # refuses a second import into a non-empty system
    with pytest.raises(Exception):
        call_command("import_v1", str(db), stdout=io.StringIO())


def test_v1_hash_formats():
    from werkzeug.security import generate_password_hash
    from core.hashers import WerkzeugImportedHasher, from_werkzeug
    h = WerkzeugImportedHasher()
    for method in ("scrypt", "pbkdf2:sha256:1000"):
        compact = from_werkzeug(generate_password_hash("Secret-123", method=method))
        assert len(compact) <= 128
        assert h.verify("Secret-123", compact) and not h.verify("secret-123", compact)
