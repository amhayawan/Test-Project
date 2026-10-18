"""Copy all data from the v1 desktop CRM (its crm.db file) into this system.

    python manage.py import_v1 "C:\\Users\\...\\AppData\\Roaming\\HAZ-CRM\\crm.db"

The target must not contain donors or cases yet. Record IDs, receipt numbers, passwords,
case documents and the v1 audit history are kept. Run `seed_defaults` first.
"""
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils import timezone

from accounts.models import User
from cases.models import Aid, Beneficiary, CaseNeed, FamilyMember
from core.hashers import from_werkzeug
from core.models import Attachment, AuditLog, Sequence
from crm.models import Donation, Donor, Member, Sponsorship, Volunteer

ROLE_MAP = {"admin": "admin", "case_manager": "case_manager", "researcher": "researcher", "staff": "fundraising"}


def _d(value):
    return date.fromisoformat(value[:10]) if value else None


def _dt(value):
    if not value:
        return None
    return timezone.make_aware(datetime.fromisoformat(value.replace(" ", "T")[:26]))


def _dec(value):
    return Decimal(str(value)) if value not in (None, "") else None


class Command(BaseCommand):
    help = "Import everything from a v1 HAZ-CRM database file."

    def add_arguments(self, parser):
        parser.add_argument("v1_db", help="path to the v1 crm.db file")
        parser.add_argument("--uploads", help="v1 uploads folder (default: next to crm.db)")

    def handle(self, v1_db, uploads=None, **options):
        path = Path(v1_db)
        if not path.exists():
            raise CommandError(f"Not found: {path}")
        if Donor.objects.exists() or Beneficiary.objects.exists():
            raise CommandError("This system already has donors or cases. Import only into an empty system.")
        if not Group.objects.filter(name="admin").exists():
            raise CommandError("Run `python manage.py seed_defaults` first.")
        uploads = Path(uploads) if uploads else path.parent / "uploads"
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        tables = {r[0] for r in src.execute("select name from sqlite_master where type='table'")}

        def rows(table):
            return list(src.execute(f'select * from "{table}"')) if table in tables else []

        def col(row, name, default=None):
            return row[name] if name in row.keys() else default

        counts = {}
        with transaction.atomic():
            users = {}
            for r in rows("user"):
                u = User.objects.filter(username=r["username"]).first() or User(username=r["username"])
                u.name_ar = r["name"]
                u.is_active = bool(r["active"])
                u.password = from_werkzeug(r["password_hash"])
                if r["role"] == "admin":
                    u.is_staff = True
                u.save()
                group = Group.objects.get(name=ROLE_MAP.get(r["role"], "fundraising"))
                u.groups.add(group)
                users[r["id"]] = u
            counts["users"] = len(users)

            for r in rows("donor"):
                Donor.objects.create(id=r["id"], name=r["name"], donor_type=r["donor_type"], phone=r["phone"] or "",
                                     email=r["email"] or "", address=r["address"] or "", notes=r["notes"] or "")
            counts["donors"] = len(rows("donor"))

            status_map = {"under_study": "under_study", "recommended": "recommended", "approved": "approved",
                          "rejected": "rejected", "suspended": "suspended"}
            per_year = {}
            for r in sorted(rows("beneficiary"), key=lambda r: (r["created_at"] or "", r["id"])):
                created = _dt(r["created_at"]) or timezone.now()
                per_year[created.year] = per_year.get(created.year, 0) + 1
                b = Beneficiary(
                    id=r["id"], case_no=f"C-{created.year}-{per_year[created.year]:05d}", name=r["name"],
                    national_id=r["national_id"] or None, phone=r["phone"] or "", area=r["area"] or "",
                    address=r["address"] or "", category=r["category"], family_size=r["family_size"] or 1,
                    monthly_income=_dec(r["monthly_income"]) or 0, status=status_map.get(r["status"], "under_study"),
                    notes=r["notes"] or "",
                    researcher=users.get(col(r, "researcher_id")), visit_date=_d(col(r, "visit_date")),
                    zakat_eligible=col(r, "zakat_eligible") or "", housing_type=col(r, "housing_type") or "",
                    housing_condition=col(r, "housing_condition") or "",
                    health_summary=col(r, "health_summary") or "", debts=_dec(col(r, "debts")),
                    research_findings=col(r, "research_findings") or "",
                    recommendation=col(r, "recommendation") or "")
                b.save()
                Beneficiary.objects.filter(pk=b.pk).update(created_at=created)
            for year, n in per_year.items():
                Sequence.objects.update_or_create(key="case", period=year, defaults={"last_value": n})
            counts["cases"] = sum(per_year.values())

            for r in rows("family_member"):
                FamilyMember.objects.create(
                    id=r["id"], beneficiary_id=r["beneficiary_id"], name=r["name"], relation=r["relation"],
                    birth_year=r["birth_year"], gender=r["gender"] or "", education_work=r["education_work"] or "",
                    health=r["health"] or "", monthly_income=_dec(r["monthly_income"]))
            counts["family members"] = len(rows("family_member"))

            for r in rows("case_need"):
                CaseNeed.objects.create(
                    id=r["id"], beneficiary_id=r["beneficiary_id"], need_type=r["need_type"],
                    description=r["description"], amount_needed=_dec(r["amount_needed"]), frequency=r["frequency"],
                    priority=r["priority"], is_open=r["status"] != "closed")
            counts["needs"] = len(rows("case_need"))

            for r in rows("sponsorship"):
                Sponsorship.objects.create(
                    id=r["id"], donor_id=r["donor_id"], beneficiary_id=r["beneficiary_id"], need_id=r["need_id"],
                    monthly_amount=_dec(r["monthly_amount"]), start_date=_d(r["start_date"]),
                    end_date=_d(r["end_date"]), status=r["status"], notes=r["notes"] or "")
            counts["sponsorships"] = len(rows("sponsorship"))

            receipts = {}
            donations = []
            for r in rows("donation"):
                donations.append(Donation(
                    id=r["id"], receipt_no=r["receipt_no"], donor_id=r["donor_id"], amount=_dec(r["amount"]),
                    method=r["method"], purpose=r["purpose"], donation_date=_d(r["donation_date"]),
                    notes=r["notes"] or "", recorded_by=users.get(r["recorded_by_id"]),
                    beneficiary_id=col(r, "beneficiary_id"), need_id=col(r, "need_id"),
                    sponsorship_id=col(r, "sponsorship_id")))
                year, seq = r["receipt_no"].split("-")[1:3]
                receipts[int(year)] = max(receipts.get(int(year), 0), int(seq))
            Donation.objects.bulk_create(donations)  # bulk: keeps v1 receipt numbers as they are
            for year, n in receipts.items():
                Sequence.objects.update_or_create(key="receipt", period=year, defaults={"last_value": n})
            counts["donations"] = len(donations)

            aid_years = {}
            for r in sorted(rows("aid"), key=lambda r: (r["aid_date"], r["id"])):
                d = _d(r["aid_date"])
                aid_years[d.year] = aid_years.get(d.year, 0) + 1
                Aid.objects.bulk_create([Aid(
                    id=r["id"], aid_no=f"A-{d.year}-{aid_years[d.year]:05d}", beneficiary_id=r["beneficiary_id"],
                    aid_type=r["aid_type"], value=_dec(r["value"]), description=r["description"] or "",
                    status=Aid.DELIVERED, delivered_on=d, requested_by=users.get(r["recorded_by_id"]))])
            for year, n in aid_years.items():
                Sequence.objects.update_or_create(key="aid", period=year, defaults={"last_value": n})
            counts["aid (delivered)"] = sum(aid_years.values())

            for r in rows("volunteer"):
                Volunteer.objects.create(id=r["id"], name=r["name"], phone=r["phone"] or "", email=r["email"] or "",
                                         skills=r["skills"] or "", availability=r["availability"] or "",
                                         join_date=_d(r["join_date"]), is_active=r["status"] == "active",
                                         notes=r["notes"] or "")
            counts["volunteers"] = len(rows("volunteer"))
            for r in rows("member"):
                Member.objects.create(id=r["id"], membership_no=r["membership_no"], name=r["name"],
                                      national_id=r["national_id"] or None, phone=r["phone"] or "",
                                      join_date=_d(r["join_date"]), paid_until_year=r["paid_until_year"],
                                      status=r["status"], notes=r["notes"] or "")
            counts["members"] = len(rows("member"))

            docs = 0
            ct = ContentType.objects.get_for_model(Beneficiary)
            for r in rows("case_document"):
                src_file = uploads / str(r["beneficiary_id"]) / r["stored_name"]
                if not src_file.exists():
                    self.stderr.write(f"missing document file: {src_file}")
                    continue
                with src_file.open("rb") as fh:
                    att = Attachment(content_type=ct, object_id=r["beneficiary_id"], title=r["title"],
                                     doc_type="case_document", original_name=r["original_name"] or "",
                                     size=r["size"] or 0, uploaded_by=users.get(r["uploaded_by_id"]))
                    att.file.save(r["stored_name"], File(fh), save=True)
                docs += 1
            counts["documents"] = docs

            history = [AuditLog(user=users.get(r["user_id"]), username=r["username"] or "", ip=r["ip"],
                                action=f"v1:{r['action']}", object_id=str(r["record_id"] or ""),
                                object_repr=r["entity"] or "", summary=(r["summary"] or "")[:500])
                       for r in rows("audit_log")]
            created = AuditLog.objects.bulk_create(history)
            for log, r in zip(created, rows("audit_log")):
                AuditLog.objects.filter(pk=log.pk).update(at=_dt(r["at"]))
            counts["v1 audit history"] = len(history)

            # v1 cases already waiting for approval get an open approval request, so a manager can act
            from approvals.models import ApprovalRequest
            from approvals.services import policy_for
            waiting = 0
            for case in Beneficiary.objects.filter(status=Beneficiary.RECOMMENDED):
                maker = case.researcher or next(iter(users.values()))
                ApprovalRequest.objects.create(
                    content_type=ContentType.objects.get_for_model(Beneficiary), object_id=case.pk,
                    doc_type=case.approval_doc_type, title=case.approval_title(), amount=None,
                    policy=policy_for(case.approval_doc_type, None), maker=maker,
                    maker_note=case.recommendation[:500])
                waiting += 1
            counts["cases waiting for approval"] = waiting

            # keep auto-numbered IDs counting after the imported ones (PostgreSQL)
            models = [User, Donor, Beneficiary, FamilyMember, CaseNeed, Sponsorship, Donation, Aid, Volunteer, Member]
            with connection.cursor() as cursor:
                for sql in connection.ops.sequence_reset_sql(no_style(), models):
                    cursor.execute(sql)
        src.close()
        for name, n in counts.items():
            self.stdout.write(f"  {name}: {n}")
        self.stdout.write(self.style.SUCCESS("Import complete. Users keep their v1 passwords."))
