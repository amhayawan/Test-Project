"""Fictional sample data for demonstrations and screenshots.

Every name, phone number and national ID here is invented. Loading refuses to run
on a database that already has records, so it can never mix with real data.
"""

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from .models import (Aid, Beneficiary, CaseNeed, Donation, Donor, FamilyMember, Member, Sponsorship, User,
                     Volunteer, db)

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
                                 ("manager", "د. هالة منصور — مديرة إدارة الحالات", "case_manager"),
                                 ("researcher", "سامح فهمي — باحث اجتماعي", "researcher"),
                                 ("researcher2", "منى السيد — باحثة اجتماعية", "researcher")]:
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

    # ---- case management: researchers, social research, family, needs
    researchers = [users["researcher"], users["researcher2"]]
    relations_kids = ["son", "daughter"]
    for i, b in enumerate(beneficiaries):
        if b.status == "under_study" and i % 3 == 0:
            continue  # left unassigned on purpose, waiting for the manager
        b.researcher_id = researchers[i % 2].id
        if b.status == "under_study" and i % 2:
            continue  # assigned, research not started
        b.visit_date = (b.created_at + timedelta(days=rng.randint(3, 15))).date()
        b.zakat_eligible = "no" if b.monthly_income and b.monthly_income >= 2000 else "yes"
        b.housing_type = rng.choice(["rent_old", "rent_new", "relatives", "owned"])
        b.housing_condition = rng.choice(["fair", "poor", "poor", "unsafe", "good"])
        b.health_summary = {"sick": "مرض مزمن يحتاج علاجاً شهرياً", "disabled": "إعاقة حركية لأحد الأبناء",
                            "elderly": "ضغط وسكر"}.get(b.category)
        b.debts = Decimal(rng.choice([0, 0, 1500, 3000, 6000]))
        b.research_findings = rng.choice([
            "تمت الزيارة الميدانية. المسكن غرفتان بالإيجار، الدخل غير ثابت من أعمال يومية. تم الاطلاع على البطاقات وشهادات الميلاد.",
            "الأسرة تعيش مع الأقارب بعد وفاة العائل. الأبناء في مراحل التعليم المختلفة. تم التحقق من الدخل من الجيران.",
            "الحالة الصحية تستهلك معظم الدخل. تم الاطلاع على التقارير الطبية وروشتات العلاج الشهري.",
        ])
        b.recommendation = rng.choice(["قبول — إعانة شهرية", "قبول — كفالة الأبناء + كرتونة شهرية",
                                       "قبول — المساهمة في العلاج", "قبول — إعانة مؤقتة لمدة 6 أشهر"])
        if b.status in ("approved", "rejected", "suspended"):
            b.reviewed_by_id = users["manager"].id
            b.reviewed_at = datetime.combine(b.visit_date + timedelta(days=rng.randint(1, 7)), datetime.min.time())
            if b.status != "approved":
                b.review_note = "الدخل يتجاوز حد الاستحقاق" if b.status == "rejected" else "تحسن دخل الأسرة"
        elif b.status == "under_study" and i % 4 == 2:
            b.status = "recommended"
        # family members
        b.family.append(FamilyMember(name=b.name.replace("أسرة ", ""), relation="head",
                                     birth_year=rng.randint(1965, 1990), gender="m" if b.category != "widow" else "f",
                                     education_work=rng.choice(["عامل يومية", "بدون عمل", "ربة منزل", "بائع متجول"]),
                                     monthly_income=b.monthly_income))
        for _ in range(max(0, (b.family_size or 1) - 1)):
            rel = rng.choice(relations_kids)
            age = rng.randint(2, 20)
            b.family.append(FamilyMember(name=f"{rng.choice(FEMALE if rel == 'daughter' else FIRST)} {b.name.split()[-1]}",
                                         relation=rel, birth_year=year - age, gender="f" if rel == "daughter" else "m",
                                         education_work=("رياض أطفال" if age < 6 else "ابتدائي" if age < 12
                                                         else "إعدادي / ثانوي" if age < 18 else "جامعة"),
                                         health="إعاقة حركية" if b.category == "disabled" and rng.random() < .5 else None))
        b.family_size = len(b.family)
        # needs
        if b.category in ("sick", "disabled"):
            b.needs.append(CaseNeed(need_type="medical", description=rng.choice(
                ["عملية جراحية عاجلة", "علاج شهري — أدوية مزمنة", "كرسي متحرك وجلسات علاج طبيعي"]),
                amount_needed=Decimal(rng.choice([8000, 15000, 25000])), priority="urgent", frequency="once"))
        if b.category in ("orphan", "widow", "poor_family"):
            b.needs.append(CaseNeed(need_type="monthly", description="إعانة شهرية للأسرة",
                                    amount_needed=Decimal(rng.choice([600, 800, 1000])), priority="high", frequency="monthly"))
        if rng.random() < .35:
            b.needs.append(CaseNeed(need_type=rng.choice(["education", "housing", "debt"]), description=rng.choice(
                ["مصروفات مدرسية ومستلزمات", "ترميم سقف الغرفة", "سداد إيجار متأخر"]),
                amount_needed=Decimal(rng.choice([1500, 3000, 5000])), priority=rng.choice(["normal", "high"]), frequency="once"))
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

    # ---- sponsorships (monthly) and donations earmarked to needs
    sponsors = [d for d in donors if d.donor_type == "individual"][:10]
    sponsored = [b for b in approved if b.category in ("orphan", "widow", "poor_family")][:10]
    for donor, case in zip(sponsors, sponsored):
        need = next((n for n in case.needs if n.frequency == "monthly"), None)
        start = date(year, rng.randint(1, 6), 1)
        sp = Sponsorship(donor=donor, beneficiary=case, need=need, monthly_amount=Decimal(rng.choice([500, 750, 1000])),
                         start_date=start, status="active")
        db.session.add(sp)
        db.session.flush()
        last_paid = today.month - (1 if rng.random() < .4 else 0)
        for month in range(start.month, last_paid + 1):
            seq += 1
            db.session.add(Donation(receipt_no=f"R-{year}-{seq:05d}", donor=donor, amount=sp.monthly_amount,
                                    method=rng.choice(["cash", "instapay", "bank"]), purpose="orphans",
                                    donation_date=_day(rng, year, month, today), beneficiary=case, need=need,
                                    sponsorship_id=sp.id, recorded_by=users["accountant"]))
    one_off = [n for b in approved for n in b.needs if n.frequency == "once"]
    for need in one_off[: len(one_off) * 2 // 3]:
        share = rng.choice([0.3, 0.5, 1.0, 1.0])
        donor = rng.choice(donors)
        seq += 1
        db.session.add(Donation(receipt_no=f"R-{year}-{seq:05d}", donor=donor,
                                amount=(need.amount_needed * Decimal(str(share))).quantize(Decimal("1")),
                                method=rng.choice(["bank", "cash", "instapay"]),
                                purpose="zakat" if need.beneficiary.zakat_eligible == "yes" else "medical",
                                donation_date=_day(rng, year, rng.randint(max(1, today.month - 3), today.month), today),
                                beneficiary=need.beneficiary, need=need, recorded_by=users["accountant"]))

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
            "aid": Aid.query.count(), "needs": CaseNeed.query.count(), "sponsorships": Sponsorship.query.count(),
            "volunteers": 14, "members": 36}
