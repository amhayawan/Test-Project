"""Fictional sample data for demonstrations and screenshots.

Every name, phone number and national ID here is invented. Loading refuses to run
on a database that already has records, so it can never mix with real data.
"""

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from .models import Aid, Beneficiary, Donation, Donor, Member, User, Volunteer, db

FIRST = ["محمد", "أحمد", "محمود", "مصطفى", "عمرو", "خالد", "طارق", "ياسر", "هشام", "إبراهيم",
         "يوسف", "عمر", "علي", "حسن", "سامح", "شريف", "كريم", "وليد", "عادل", "رامي"]
FEMALE = ["فاطمة", "مريم", "سارة", "نادية", "هبة", "منى", "إيمان", "سعاد", "عزة", "رشا",
          "أمل", "دعاء", "نجلاء", "هالة", "سهام", "زينب", "آمال", "وفاء"]
LAST = ["عبد الرحمن", "السيد", "حسين", "إبراهيم", "عبد الله", "منصور", "الشريف", "سليمان",
        "عبد العزيز", "فهمي", "النجار", "رمضان", "عثمان", "حجازي", "الجمال", "بدوي", "صبري", "زكي"]
COMPANIES = ["شركة النيل للمقاولات", "مجموعة الدلتا للتجارة", "صيدليات الشفاء", "مخابز الأمل",
             "شركة المستقبل للأغذية", "مكتب الهدى للمحاسبة", "معرض النور للأثاث"]
AREAS = ["إمبابة", "بولاق الدكرور", "الوراق", "المنيرة الغربية", "كرداسة", "أوسيم", "البراجيل"]
SKILLS = ["توزيع ميداني", "بحث اجتماعي", "تصوير وتوثيق", "إدخال بيانات", "تدريس ومتابعة طلاب",
          "طبيب متطوع", "قيادة سيارة", "تنظيم فعاليات"]

# Rough Egyptian giving calendar for 2026: Ramadan ~ Feb 18 - Mar 19, Eid al-Adha ~ May 27.
MONTH_WEIGHT = {1: 1.0, 2: 2.2, 3: 3.0, 4: 1.0, 5: 1.8, 6: 0.9, 7: 0.8, 8: 0.9, 9: 1.2, 10: 0.9}


def _name(rng, female=False):
    return f"{rng.choice(FEMALE if female else FIRST)} {rng.choice(FIRST)} {rng.choice(LAST)}"


def _phone(rng):
    return rng.choice(["010", "011", "012", "015"]) + f"{rng.randint(0, 99999999):08d}"


def _nid(rng, used):
    while True:
        birth = date(rng.randint(1950, 2004), rng.randint(1, 12), rng.randint(1, 28))
        century = "2" if birth.year < 2000 else "3"
        nid = f"{century}{birth:%y%m%d}21{rng.randint(0, 99999):05d}"
        if nid not in used:
            used.add(nid)
            return nid


def _day(rng, year, month, last_day):
    end = last_day.day if (year, month) == (last_day.year, last_day.month) else 28
    return date(year, month, rng.randint(1, end))


def has_data():
    return any(m.query.first() for m in (Donor, Donation, Beneficiary, Aid, Volunteer, Member))


def load_demo_data(admin_password="demo1234", seed=7, today=None):
    """Fill an empty database with fictional records. Returns counts per table."""
    if has_data():
        raise RuntimeError("The database already has records. Demo data is only loaded into an empty database.")
    rng = random.Random(seed)
    today = today or date.today()
    year = today.year
    used_nids = set()

    users = {}
    for username, name, role in [("admin", "مدير النظام", "admin"),
                                 ("accountant", "نهى عبد الله — المحاسبة", "staff"),
                                 ("researcher", "سامح فهمي — البحث الاجتماعي", "staff")]:
        u = User.query.filter_by(username=username).first()
        if not u:
            u = User(username=username, name=name, role=role)
            u.set_password(admin_password)
            db.session.add(u)
        users[username] = u
    db.session.flush()

    donors = []
    for i in range(32):
        company = i < len(COMPANIES)
        donors.append(Donor(
            name=COMPANIES[i] if company else _name(rng, female=rng.random() < 0.35),
            donor_type="company" if company else "individual",
            phone=_phone(rng),
            address=f"{rng.choice(AREAS)}، الجيزة",
            created_at=datetime(year, 1, 1) + timedelta(days=rng.randint(0, 120)),
        ))
    db.session.add_all(donors)
    db.session.flush()

    purposes_by_month = {2: ["zakat", "food", "sadaqa", "zakat_fitr"], 3: ["zakat", "food", "zakat_fitr", "sadaqa"],
                         5: ["udhiya", "udhiya", "general", "orphans"]}
    seq = 0
    for month in range(1, today.month + 1):
        count = int(14 * MONTH_WEIGHT.get(month, 1.0))
        for _ in range(count):
            donor = rng.choice(donors)
            big = donor.donor_type == "company"
            amount = rng.choice([5000, 10000, 15000, 25000] if big else [100, 200, 300, 500, 500, 1000, 1500, 2000, 3000])
            purpose = rng.choice(purposes_by_month.get(month, ["general", "orphans", "medical", "education", "sadaqa", "zakat"]))
            seq += 1
            db.session.add(Donation(
                receipt_no=f"R-{year}-{seq:05d}", donor=donor, amount=Decimal(amount),
                method=rng.choice(["cash", "cash", "bank", "instapay", "wallet"] if not big else ["bank", "check"]),
                purpose=purpose, donation_date=_day(rng, year, month, today),
                recorded_by=users["accountant"],
            ))

    categories = ["poor_family"] * 5 + ["widow"] * 4 + ["orphan"] * 3 + ["elderly"] * 2 + ["sick"] * 2 + ["disabled", "student"]
    beneficiaries = []
    for i in range(46):
        cat = rng.choice(categories)
        status = "approved" if i < 34 else rng.choice(["under_study", "under_study", "rejected", "suspended"])
        beneficiaries.append(Beneficiary(
            name=("أسرة " + _name(rng)) if cat == "poor_family" else _name(rng, female=cat in ("widow",)),
            national_id=_nid(rng, used_nids), phone=_phone(rng),
            area=rng.choice(AREAS), address="شارع " + rng.choice(["الجمهورية", "النصر", "المحطة", "السوق", "المدارس"]),
            category=cat, family_size=rng.randint(2, 8) if cat != "elderly" else rng.randint(1, 2),
            monthly_income=Decimal(rng.choice([0, 600, 900, 1200, 1500, 1800, 2200])),
            status=status,
            notes="تم البحث الميداني والتحقق من المستندات." if status == "approved" else "في انتظار زيارة الباحث الاجتماعي.",
            created_at=datetime(year, 1, 1) + timedelta(days=rng.randint(0, 200)),
        ))
    db.session.add_all(beneficiaries)
    db.session.flush()

    approved = [b for b in beneficiaries if b.status == "approved"]
    for month in range(1, today.month + 1):
        for b in rng.sample(approved, k=min(len(approved), int(9 * MONTH_WEIGHT.get(month, 1.0)))):
            if month in (2, 3):
                kind, value, desc = "food", rng.choice([350, 450, 500]), "كرتونة رمضان"
            elif month == 5 and rng.random() < 0.6:
                kind, value, desc = "food", rng.choice([400, 600]), "لحوم أضاحي"
            elif b.category == "sick":
                kind, value, desc = "medical", rng.choice([500, 800, 1200]), "علاج شهري"
            elif b.category in ("orphan", "student") and month == 9:
                kind, value, desc = "education", rng.choice([600, 900]), "مستلزمات دراسية"
            else:
                kind, value, desc = "cash", rng.choice([300, 400, 500, 700]), "إعانة شهرية"
            db.session.add(Aid(beneficiary=b, aid_type=kind, value=Decimal(value),
                               aid_date=_day(rng, year, month, today), description=desc,
                               recorded_by=users["researcher"]))

    for i in range(14):
        db.session.add(Volunteer(
            name=_name(rng, female=rng.random() < 0.5), phone=_phone(rng),
            skills="، ".join(rng.sample(SKILLS, 2)), availability=rng.choice(["الجمعة والسبت", "مساءً", "أيام الإجازات"]),
            join_date=date(year - rng.randint(0, 3), rng.randint(1, 12), 1),
            status="active" if i < 11 else "inactive"))

    for i in range(36):
        db.session.add(Member(
            membership_no=str(101 + i), name=_name(rng, female=rng.random() < 0.3),
            national_id=_nid(rng, used_nids), phone=_phone(rng),
            join_date=date(rng.randint(2012, year - 1), rng.randint(1, 12), 1),
            paid_until_year=year if i < 27 else year - 1,
            status="honorary" if i < 2 else "active"))

    db.session.commit()
    return {"donors": len(donors), "donations": seq, "beneficiaries": len(beneficiaries),
            "aid": Aid.query.count(), "volunteers": 14, "members": 36}
