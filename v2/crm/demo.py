"""Demo donors, campaigns and a year of donations (all fictional)."""
from datetime import date, timedelta
from decimal import Decimal

from .models import Campaign, Donation, Donor, Member, Volunteer

FIRST = ["محمد", "أحمد", "محمود", "مصطفى", "عمر", "خالد", "إبراهيم", "يوسف", "حسن", "علي", "فاطمة", "مريم", "نور",
         "سلمى", "هدى", "دينا", "رحاب", "إيمان", "شيماء", "آية"]
LAST = ["عبد الرحمن", "السيد", "الشريف", "منصور", "عثمان", "الجمال", "رضوان", "سليمان", "فرج", "الصاوي", "زكي",
        "النجار", "حمدي", "عبد العزيز", "رشدي"]
COMPANIES = ["شركة النيل للتجارة", "مؤسسة الخير للمقاولات", "مجموعة الدلتا للأغذية", "صيدليات الشفاء",
             "شركة المستقبل للبرمجيات", "مصنع الأمل للملابس"]
PURPOSES = [("general", 30), ("zakat", 22), ("sadaqa", 14), ("orphans", 10), ("medical", 9), ("food", 9),
            ("zakat_fitr", 3), ("education", 3)]
METHODS = [("cash", 30), ("bank", 30), ("instapay", 25), ("wallet", 10), ("check", 5)]


def person(rng):
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def pick(rng, weighted):
    return rng.choices([k for k, _ in weighted], [w for _, w in weighted])[0]


def run(ctx):
    rng, today = ctx.rng, ctx.today
    donors = [Donor.objects.create(name=person(rng), phone=f"010{rng.randrange(10**7, 10**8)}",
                                   address=rng.choice(["مدينة نصر", "المعادي", "الدقي", "شبرا", "حلوان", "6 أكتوبر"]))
              for _ in range(34)]
    donors += [Donor.objects.create(name=c, donor_type=Donor.COMPANY, phone=f"02{rng.randrange(10**7, 10**8)}")
               for c in COMPANIES]
    ctx.donors = donors
    y = today.year
    ctx.campaign = {
        "RMD": Campaign.objects.create(code=f"RMD{y}", name=f"حملة رمضان {y}", target=Decimal(400000),
                                       start_date=date(y, 2, 1), end_date=date(y, 4, 10), fund=ctx.fund["GEN"],
                                       project=ctx.project["FOOD"]),
        "ORPH": Campaign.objects.create(code=f"ORPH{y}", name="اكفل يتيماً", target=Decimal(600000),
                                        start_date=date(y, 1, 1), fund=ctx.fund["ORPH"], project=ctx.project["ORPH"]),
        "MED": Campaign.objects.create(code=f"MED{y}", name="قافلة الشفاء الطبية", target=Decimal(250000),
                                       start_date=date(y, 5, 1), end_date=date(y, 9, 30), fund=ctx.fund["MED"],
                                       project=ctx.project["MED"]),
    }
    start = today - timedelta(days=365)
    fund_for = {"zakat": "ZAK", "zakat_fitr": "ZAK", "orphans": "ORPH", "medical": "MED"}
    for _ in range(420):
        day = start + timedelta(days=rng.randrange(0, 366))
        purpose = pick(rng, PURPOSES)
        campaign = None
        if purpose == "orphans":
            campaign = ctx.campaign["ORPH"]
        elif purpose == "medical" and ctx.campaign["MED"].start_date <= day:
            campaign = ctx.campaign["MED"]
        elif purpose == "food" and ctx.campaign["RMD"].start_date <= day <= ctx.campaign["RMD"].end_date:
            campaign = ctx.campaign["RMD"]
        donor = rng.choice(donors)
        big = donor.donor_type == Donor.COMPANY
        amount = Decimal(rng.choice([500, 1000, 1000, 2000, 2500, 3000, 5000, 7500, 10000]) * (12 if big else 1))
        Donation.objects.create(donor=donor, amount=amount, method="bank" if big else pick(rng, METHODS),
                                purpose=purpose, donation_date=day, fund=ctx.fund[fund_for.get(purpose, "GEN")],
                                campaign=campaign, recorded_by=ctx.u["fundraiser"])
    for i in range(8):
        Volunteer.objects.create(name=person(rng), phone=f"011{rng.randrange(10**7, 10**8)}")
    for i in range(12):
        Member.objects.create(membership_no=f"M-{i + 1:03d}", name=person(rng))
