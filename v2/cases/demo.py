"""Demo cases at every stage, with research, family, needs, sponsorships, earmarked donations and aid."""
from datetime import timedelta
from decimal import Decimal

from approvals import services
from crm.demo import person
from crm.models import Donation, Sponsorship

from .models import Aid, Beneficiary, CaseNeed, FamilyMember, HouseholdItem, MedicalCondition

AREAS = ["عزبة النخل", "المطرية", "دار السلام", "منشأة ناصر", "الخصوص", "بولاق الدكرور", "إمبابة", "حلوان"]
NEEDS = [("monthly", "دعم شهري للأسرة", 1500, "monthly"), ("medical", "عملية جراحية / علاج", 18000, "once"),
         ("education", "مصروفات مدارس ومستلزمات", 3500, "once"), ("housing", "ترميم سقف ودورة مياه", 12000, "once"),
         ("food", "شنطة غذائية شهرية", 600, "monthly")]


def run(ctx):
    rng, today, u = ctx.rng, ctx.today, ctx.u
    researchers = [u["researcher1"], u["researcher2"]]
    cases = []
    for i in range(30):
        category = rng.choice(["poor_family", "orphan", "orphan", "widow", "elderly", "sick", "disabled", "student"])
        project = {"orphan": ctx.project["ORPH"], "sick": ctx.project["MED"]}.get(category, ctx.project["FOOD"])
        c = Beneficiary.objects.create(
            name=person(rng), phone=f"012{rng.randrange(10**7, 10**8)}", area=rng.choice(AREAS), category=category,
            family_size=rng.randint(2, 8), monthly_income=Decimal(rng.choice([0, 800, 1200, 2000, 2500])),
            department=ctx.dept["RES"], project=project, created_by=u["casemanager"],
            researcher=None if i < 3 else researchers[i % 2])
        cases.append(c)
    # stage 1: 3 unassigned, 4 under research; stage 2: 4 recommended; stage 3: 17 approved; 2 rejected
    for i, c in enumerate(cases[3:], start=3):
        if i < 7:
            continue
        c.visit_date = today - timedelta(days=rng.randint(20, 300))
        c.zakat_eligible = rng.choice(["yes", "yes", "no"])
        c.housing_type = rng.choice(["rent_old", "rent_new", "relatives", "owned"])
        c.housing_condition = rng.choice(["fair", "poor", "unsafe"])
        c.research_findings = "تمت الزيارة الميدانية؛ الأسرة بلا دخل ثابت وتحتاج إلى دعم."
        c.recommendation = "قبول الحالة ودعم الاحتياجات الأساسية."
        # the standard research form
        c.form_no = f"RF-{i + 1:04d}"
        c.marital_status = {"widow": "widow", "orphan": "widow"}.get(c.category, rng.choice(["married_m", "divorced", "widow"]))
        c.income_salaries = Decimal(rng.choice([0, 0, 1500, 2500]))
        c.income_takaful = Decimal(rng.choice([0, 600, 750, 900]))
        c.income_insurance = Decimal(rng.choice([0, 0, 1100]))
        c.income_charities = Decimal(rng.choice([0, 200, 300]))
        c.income_benefactors, c.benefactors_who = Decimal(rng.choice([0, 300, 500])), "أقارب"
        c.exp_food_daily = Decimal(rng.choice([60, 80, 100, 120]))
        c.exp_rent = Decimal(rng.choice([300, 600, 1200])) if c.housing_type.startswith("rent") else Decimal(0)
        c.exp_transport, c.exp_education = Decimal(rng.choice([100, 200])), Decimal(rng.choice([0, 250, 500]))
        c.exp_electricity, c.exp_water, c.exp_gas = Decimal(rng.choice([120, 200])), Decimal(40), Decimal(rng.choice([0, 110]))
        c.rooms, c.house_area = rng.randint(1, 3), f"{rng.choice([30, 45, 60])} م²"
        c.bathroom = rng.choice(["private", "shared"])
        c.floor_type = rng.choice(["tiles", "ceramic", "other"])
        c.building_material = rng.choice(["rural", "brick", "plastered"])
        c.water_connection = rng.choice(["yes", "yes", "no"])
        c.needs_roof = rng.choice(["no", "no", "yes"])
        c.ration_card_members = c.family_size
        c.livestock, c.smoker = "no", rng.choice(["yes", "no"])
        c.need_monthly = True
        c.need_medical = c.category in ("sick", "disabled")
        c.need_appliances = rng.random() < 0.3
        c.assessment = "urgent" if i < 24 else "medium"
        c.save()
        FamilyMember.objects.create(beneficiary=c, name=c.name, relation="head", age=rng.randint(30, 65),
                                    education=rng.choice(["أمي", "ابتدائي", "دبلوم"]),
                                    education_work=rng.choice(["عامل باليومية", "لا يعمل", "بائع متجول"]),
                                    job_stability=rng.choice(["irregular", "stable"]), able_to_work=rng.choice(["yes", "no"]))
        for _ in range(rng.randint(1, 3)):
            FamilyMember.objects.create(beneficiary=c, name=person(rng), relation=rng.choice(["son", "daughter"]),
                                        age=rng.randint(4, 17), education=rng.choice(["ابتدائي", "إعدادي", "ثانوي"]))
        if c.category == "sick":
            MedicalCondition.objects.create(beneficiary=c, patient=c.name, illness="مرض مزمن بالقلب",
                                            treatment_cost=Decimal(rng.choice([800, 1500])), state_coverage="جزئياً")
        for item in c.household.all():
            if item.kind == HouseholdItem.APPLIANCE:
                item.present = rng.choice(["yes", "yes", "no"])
                item.condition = rng.choice(["medium", "poor"]) if item.present == "yes" else ""
            else:
                item.count = rng.randint(0, 3)
                item.condition = rng.choice(["medium", "poor"]) if item.count else ""
            item.save()
        req = services.submit(c, c.researcher, note="البحث مكتمل")
        if i < 11:
            continue                                  # waiting for the case manager
        if i >= 28:
            services.decide(req, u["casemanager"], "reject", "لا تنطبق شروط الاستحقاق")
            continue
        services.decide(req, u["casemanager"], "approve")
    approved = list(Beneficiary.objects.filter(status=Beneficiary.APPROVED))
    ctx.cases = approved
    for c in approved:
        need_type, desc, amount, freq = rng.choice(NEEDS)
        CaseNeed.objects.create(beneficiary=c, need_type=need_type, description=desc, amount_needed=Decimal(amount),
                                frequency=freq, priority=rng.choice(["urgent", "high", "normal"]))
    # designated donations by case code: some needs fully collected, some partly
    for n, need in enumerate(CaseNeed.objects.filter(beneficiary__in=approved, frequency="once")[:6]):
        share = need.amount_needed if n % 2 == 0 else (need.amount_needed / 2).quantize(Decimal(1))
        Donation.objects.create(donor=rng.choice(ctx.donors), amount=share, method="bank", purpose=need.need_type
                                if need.need_type in ("medical", "education") else "general",
                                donation_date=today - timedelta(days=rng.randint(5, 60)), fund=ctx.fund["GEN"],
                                beneficiary=need.beneficiary, need=need, recorded_by=u["fundraiser"])
    # sponsorships for orphans, with monthly payments recorded as donations
    for c in [c for c in approved if c.category == "orphan"][:6]:
        donor = rng.choice(ctx.donors)
        start = today.replace(day=1) - timedelta(days=150)
        s = Sponsorship.objects.create(donor=donor, beneficiary=c, monthly_amount=Decimal(1000), start_date=start)
        d = start
        while d <= today - timedelta(days=20):
            Donation.objects.create(donor=donor, amount=Decimal(1000), method="bank", purpose="orphans",
                                    donation_date=d, fund=ctx.fund["ORPH"], beneficiary=c, sponsorship=s,
                                    campaign=ctx.campaign["ORPH"], recorded_by=u["fundraiser"])
            d = (d.replace(day=1) + timedelta(days=32)).replace(day=5)
    # aid: cash delivered over the past months, goods waiting for the store, one waiting for approval
    def give(c, aid_type, value, paid_by, fund, project, days_ago, deliver=True):
        # the Projects Department plans the aid for the referred case; its manager approves it
        aid = Aid.objects.create(beneficiary=c, aid_type=aid_type, value=Decimal(value), paid_by=paid_by,
                                 fund=fund, project=project, requested_by=u["projects"],
                                 description="مساعدة وفق البحث الاجتماعي")
        req = services.submit(aid, u["projects"])
        services.decide(req, u["pm"], "approve")
        if req.policy.steps.count() > 1:
            services.decide(req, u["director"], "approve")
        aid.refresh_from_db()
        if deliver:
            aid.mark_delivered(today - timedelta(days=days_ago))
        return aid
    for n, c in enumerate(approved):
        zakat = c.zakat_eligible == "yes"
        fund = ctx.fund["ZAK"] if zakat else ctx.fund["GEN"]
        give(c, "cash", rng.choice([1000, 1500, 2000]), "cash", fund, ctx.project["FOOD"], rng.randint(30, 200))
        if c.category == "sick":
            give(c, "medical", 12000, "bank", ctx.fund["MED"], ctx.project["MED"], rng.randint(10, 100))
    ctx.stock_aids = [give(c, "food", 900, "stock", ctx.fund["GEN"], ctx.project["FOOD"], 0, deliver=False)
                      for c in approved[:5]]
    pending = Aid.objects.create(beneficiary=approved[-1], aid_type="education", value=Decimal(3500),
                                 fund=ctx.fund["GEN"], requested_by=u["projects"], description="مصروفات مدارس")
    services.submit(pending, u["projects"])
