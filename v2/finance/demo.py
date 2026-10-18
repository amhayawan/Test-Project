"""Demo finance: opening balances, running costs paid by voucher, fixed assets and depreciation."""
from datetime import date, timedelta
from decimal import Decimal

from approvals import services

from . import assets
from .models import Account, AssetCategory, DepreciationRun, FixedAsset, JournalEntry, JournalLine, Payment

D = Decimal


def acc(code):
    return Account.objects.get(code=code)


def run(ctx):
    rng, today, u = ctx.rng, ctx.today, ctx.u
    start = date(today.year - 1, today.month, 1)
    # opening balances (maker: accountant, checker: finance manager; above the limit also the director)
    e = JournalEntry.objects.create(date=start, description="أرصدة افتتاحية (بيانات تجريبية)", source="opening",
                                    created_by=u["accountant"])
    gen, zak, orph = ctx.fund["GEN"], ctx.fund["ZAK"], ctx.fund["ORPH"]
    for code, debit, credit, fund in (("1102", 1450000, 0, gen), ("1101", 40000, 0, gen), ("1102", 320000, 0, zak),
                                      ("1102", 180000, 0, orph), ("3101", 0, 1490000, gen), ("3103", 0, 320000, zak),
                                      ("3102", 0, 180000, orph)):
        JournalLine.objects.create(entry=e, account=acc(code), debit=D(debit), credit=D(credit), fund=fund)
    req = services.submit(e, u["accountant"])
    for step_user in (u["finmanager"], u["director"]):
        if req.status == req.PENDING:
            services.decide(req, step_user, "approve")
            req.refresh_from_db()

    # monthly running costs, paid by voucher
    def pay(day, payee, amount, account, dept, desc, project=None):
        p = Payment.objects.create(date=day, payee=payee, amount=D(amount), method="bank", debit_account=acc(account),
                                   department=ctx.dept[dept], project=project, description=desc,
                                   prepared_by=u["accountant"], fund=gen)
        r = services.submit(p, u["accountant"])
        services.decide(r, u["finmanager"], "approve")
        r.refresh_from_db()
        if r.status == r.PENDING:
            services.decide(r, u["director"], "approve")
        p.refresh_from_db()
        p.mark_paid(day)

    d = start
    while d <= today:
        pay(d.replace(day=3), "مالك مقر الجمعية", 18000, "5301", "ADM", "إيجار المقر")
        pay(d.replace(day=12), "شركة الكهرباء والمياه", rng.choice([2400, 2900, 3600]), "5302", "ADM", "فواتير المرافق")
        pay(d.replace(day=15), "شركة الاتصالات", 1100, "5304", "ADM", "إنترنت وهواتف")
        d = (d + timedelta(days=32)).replace(day=1)
        if d.replace(day=15) > today:
            break
    pay(today - timedelta(days=40), "مكتب المراجعة القانونية", 25000, "5308", "FIN", "أتعاب مراجعة القوائم المالية")

    # fixed assets and the last three months of depreciation
    items = [("VEH", "ميكروباص توزيع المساعدات", 650000, 36), ("IT", "أجهزة حاسب للمكتب (5)", 120000, 12),
             ("FUR", "أثاث مكتبي", 85000, 20)]
    for cat, name, cost, months_ago in items:
        y, m = today.year, today.month - months_ago
        while m <= 0:
            y, m = y - 1, m + 12
        FixedAsset.objects.create(name=name, category=AssetCategory.objects.get(code=cat), acquired_on=date(y, m, 1),
                                  cost=D(cost), department=ctx.dept["PRG" if cat == "VEH" else "ADM"],
                                  project=ctx.project["FOOD"] if cat == "VEH" else None, fund=gen,
                                  location="المقر الرئيسي")
    for back in (3, 2, 1):
        y, m = today.year, today.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        run_ = assets.calculate(DepreciationRun.objects.create(year=y, month=m, end=date(y, m, 1)), u["accountant"])
        if run_.entry:
            r = services.submit(run_.entry, u["accountant"])
            services.decide(r, u["finmanager"], "approve")
    # one manual journal waiting for the finance manager
    e = JournalEntry.objects.create(date=today, description="تسوية مصروفات بنكية الشهر الحالي", created_by=u["accountant"])
    JournalLine.objects.create(entry=e, account=acc("5307"), debit=D(350), department=ctx.dept["FIN"], fund=gen)
    JournalLine.objects.create(entry=e, account=acc("1102"), credit=D(350), fund=gen)
    services.submit(e, u["accountant"])
