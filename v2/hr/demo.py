"""Demo staff, structure, contracts, leave and three months of payroll.

Every rate and leave figure below is SAMPLE data so the screens have numbers. They are NOT legal
values: real installs enter the official figures, signed off by the labour-law specialist.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from approvals import services
from crm.demo import person

from . import payroll
from .models import (Assignment, Contract, Employee, EmployeePayItem, Grade, Incentive, InsuranceRule, LeaveEntitlement,
                     LeaveRequest, LeaveType, PayComponent, PayrollRun, Position, PublicHoliday, TaxBracket)

SAMPLE = "SAMPLE DATA – NOT LEGAL VALUES"
D = Decimal

GRADES = [("G1", "الدرجة الأولى (قيادية)", 1, 25000, 45000), ("G2", "الدرجة الثانية (إشرافية)", 2, 15000, 26000),
          ("G3", "الدرجة الثالثة (أخصائي)", 3, 9000, 16000), ("G4", "الدرجة الرابعة (منفذ)", 4, 6500, 10000),
          ("G5", "الدرجة الخامسة (معاون)", 5, 4500, 7000)]

# username or None, position code, department, grade, salary, manager username, gender, assignments
STAFF = [
    ("director", "ED", "ADM", "G1", 38000, None, "f", []),
    ("casemanager", "CMH", "RES", "G2", 21000, "director", "f", [("MED", 40)]),
    ("projects", "CM", "PRG", "G3", 14000, "pm", "m", [("FOOD", 50)]),
    ("researcher1", "SR", "RES", "G3", 10500, "casemanager", "m", [("ORPH", 50), ("FOOD", 30)]),
    ("researcher2", "SR", "RES", "G3", 10000, "casemanager", "f", [("ORPH", 40), ("MED", 40)]),
    ("pm", "PM", "PRG", "G2", 19000, "director", "f", [("ORPH", 50), ("FOOD", 50)]),
    ("fundraiser", "FRO", "FR", "G3", 12000, "director", "m", []),
    ("hrmanager", "HRM", "HR", "G2", 20000, "director", "f", []),
    ("hrofficer", "HRO", "HR", "G4", 8500, "hrmanager", "f", []),
    ("payroll", "PAY", "FIN", "G3", 11000, "finmanager", "m", []),
    ("finmanager", "FM", "FIN", "G2", 24000, "director", "m", []),
    ("accountant", "ACC", "FIN", "G3", 11500, "finmanager", "f", []),
    ("procurement", "PRO", "SUP", "G3", 11000, "director", "m", []),
    ("storekeeper", "STK", "SUP", "G4", 8000, "procurement", "m", []),
    (None, "DRV", "ADM", "G5", 5500, "director", "m", [("FOOD", 60)]),
    (None, "SW", "RES", "G4", 7500, "casemanager", "f", [("ORPH", 100)]),
    (None, "SW", "RES", "G4", 7200, "casemanager", "f", [("FOOD", 100)]),
]
POSITIONS = {"ED": ("المدير التنفيذي", "ADM", "G1", 1), "CMH": ("مدير قسم البحث الاجتماعي", "RES", "G2", 1),
             "CM": ("أخصائي قسم المشروعات", "PRG", "G3", 2), "SR": ("باحث اجتماعي", "RES", "G3", 4),
             "PM": ("مدير قسم المشروعات", "PRG", "G2", 1), "FRO": ("مسؤول تنمية موارد", "FR", "G3", 2),
             "HRM": ("مدير الموارد البشرية", "HR", "G2", 1), "HRO": ("أخصائي موارد بشرية", "HR", "G4", 1),
             "PAY": ("مسؤول الرواتب", "FIN", "G3", 1), "FM": ("المدير المالي", "FIN", "G2", 1),
             "ACC": ("محاسب", "FIN", "G3", 2), "PRO": ("مسؤول مشتريات", "SUP", "G3", 1),
             "STK": ("أمين مخزن", "SUP", "G4", 1), "DRV": ("سائق", "ADM", "G5", 2), "SW": ("أخصائي ميداني", "RES", "G4", 3)}


def month_back(today, n):
    m = today.month - 1 - n
    return today.year + m // 12, m % 12 + 1


def run(ctx):
    rng, today, u = ctx.rng, ctx.today, ctx.u
    grade = {code: Grade.objects.create(code=code, name_ar=ar, level=lvl, min_salary=D(lo), max_salary=D(hi))
             for code, ar, lvl, lo, hi in GRADES}
    pos = {}
    for code, (ar, dept, g, n) in POSITIONS.items():
        pos[code] = Position.objects.create(code=code, name_ar=ar, department=ctx.dept[dept], grade=grade[g],
                                            headcount=n, purpose="مثال توضيحي لوصف وظيفي")
    pos["CMH"].reports_to = pos["ED"]
    pos["CMH"].save()
    emp_by_user, all_emps = {}, []
    for i, (username, p, dept, g, salary, mgr, gender, assigns) in enumerate(STAFF):
        user = u.get(username) if username else None
        hired = date(today.year - rng.randint(1, 9), rng.randint(1, 12), 1)
        e = Employee.objects.create(
            name_ar=user.name_ar if user else person(rng), name_en=user.name_en if user else "",
            national_id=f"2{rng.randint(75, 99)}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}01{i:05d}"[:14].ljust(14, "1"),
            birth_date=date(rng.randint(1970, 1998), rng.randint(1, 12), rng.randint(1, 28)), gender=gender,
            department=ctx.dept[dept], position=pos[p], grade=grade[g], user=user, hire_date=hired,
            manager=emp_by_user.get(mgr), bank_name="البنك الأهلي المصري", bank_account=f"EG{rng.randrange(10**12, 10**13)}",
            social_insurance_no=str(rng.randrange(10**7, 10**8)))
        Contract.objects.create(employee=e, contract_type="permanent", start_date=hired, basic_salary=D(salary))
        for key, pct in assigns:
            Assignment.objects.create(employee=e, department=ctx.dept["PRG"], project=ctx.project[key], percent=D(pct),
                                      start_date=hired)
        if username:
            emp_by_user[username] = e
        all_emps.append(e)
    # managers for staff whose manager was created after them
    for username, _p, _d, _g, _s, mgr, _gender, _a in STAFF:
        if username and mgr and not emp_by_user[username].manager_id:
            Employee.objects.filter(pk=emp_by_user[username].pk).update(manager=emp_by_user[mgr])
    ctx.employees = emp_by_user
    transport = PayComponent.objects.create(code="TRN", name_ar="بدل انتقال", kind="earning", taxable=True)
    loan = PayComponent.objects.create(code="LOAN", name_ar="قسط سلفة", kind="deduction")
    for e in all_emps:
        EmployeePayItem.objects.create(employee=e, component=transport, amount=D(600), start_date=e.hire_date)
    EmployeePayItem.objects.create(employee=emp_by_user["storekeeper"], component=loan, amount=D(500),
                                   start_date=date(today.year, 1, 1))

    # ---- SAMPLE statutory rules (entered so payroll can run in the demo)
    year = today.year
    for y in {year, month_back(today, 3)[0]}:
        InsuranceRule.objects.get_or_create(year=y, defaults=dict(
            employee_rate=D(11), employer_rate=D("18.75"), min_insurable=D(2300), max_insurable=D(14500),
            source=SAMPLE, verified_by="sara (demo)"))
        if not TaxBracket.objects.filter(year=y).exists():
            for lower, upper, rate in ((0, 40000, 0), (40000, 55000, 10), (55000, 70000, 15), (70000, 200000, 20),
                                       (200000, 400000, 22.5), (400000, None, 25)):
                TaxBracket.objects.create(year=y, lower=D(lower), upper=D(upper) if upper else None, rate=D(str(rate)),
                                          annual_exemption=D(20000) if lower == 0 else 0, source=SAMPLE)

    # ---- SAMPLE leave rules, entered by HR and signed off by Sara
    annual = LeaveType.objects.get(code="ANNUAL")
    for months, age, days in ((6, None, 15), (12, None, 21), (120, None, 30), (0, 50, 30)):
        LeaveEntitlement.objects.create(leave_type=annual, min_service_months=months, min_age=age, days_per_year=D(days))
    LeaveType.objects.filter(code="CASUAL").update(max_per_request=D(2), max_per_year=D(7))
    LeaveType.objects.filter(code="PERMIT").update(max_per_month=D(4))
    LeaveType.objects.filter(code__in=("UNPAID", "MATERNITY")).update(calendar_days=True)
    LeaveType.objects.filter(code="MATERNITY").update(max_times_in_service=3)
    LeaveType.objects.update(source=SAMPLE, changed_by=u["hrmanager"], verified_by=u["sara"], verified_at=timezone.now())
    for m, d, name in ((1, 7, "عيد الميلاد المجيد"), (1, 25, "عيد الشرطة / ثورة يناير"), (4, 25, "عيد تحرير سيناء"),
                       (5, 1, "عيد العمال"), (6, 30, "ذكرى 30 يونيو"), (7, 23, "عيد ثورة يوليو"),
                       (10, 6, "عيد القوات المسلحة")):
        PublicHoliday.objects.get_or_create(date=date(year, m, d), defaults={"name_ar": f"{name} ({SAMPLE})"})

    def leave(username, code, start, end, approve=True, hours=None):
        e = emp_by_user[username]
        req = LeaveRequest(employee=e, leave_type=LeaveType.objects.get(code=code), start_date=start, end_date=end,
                           hours=hours, requested_by=e.user, reason="طلب تجريبي")
        req.full_clean()
        req.save()
        ap = services.submit(req, e.user)
        if approve:
            approver = e.manager.user if e.manager and e.manager.user else u["hrmanager"]
            services.decide(ap, approver, "approve")
        return req

    def workday(d):
        while d.weekday() in (4, 5):
            d += timedelta(days=1)
        return d

    leave("researcher1", "ANNUAL", workday(today - timedelta(days=60)), workday(today - timedelta(days=60)) + timedelta(days=4))
    leave("accountant", "CASUAL", workday(today - timedelta(days=25)), workday(today - timedelta(days=25)))
    leave("hrofficer", "ANNUAL", workday(today), workday(today) + timedelta(days=2))          # away today
    leave("researcher2", "PERMIT", workday(today - timedelta(days=8)), workday(today - timedelta(days=8)), hours=D(2))
    leave("fundraiser", "ANNUAL", workday(today + timedelta(days=14)), workday(today + timedelta(days=14)) + timedelta(days=3),
          approve=False)                                                                     # waiting for the director

    # ---- payroll for the last three complete months: prepared, approved twice, paid
    y1, m1 = month_back(today, 1)
    bonus = Incentive.objects.create(employee=emp_by_user["researcher1"], kind="bonus", amount=D(1500), pay_year=y1,
                                     pay_month=m1, reason="مكافأة تميز في البحث الميداني", requested_by=u["hrofficer"])
    services.decide(services.submit(bonus, u["hrofficer"]), u["hrmanager"], "approve")
    for n in (3, 2, 1):
        y, m = month_back(today, n)
        run = payroll.calculate(PayrollRun.objects.create(year=y, month=m), u["payroll"])
        req = services.submit(run, u["payroll"])
        services.decide(req, u["hrmanager"], "approve")
        services.decide(req, u["director"], "approve")
        run.refresh_from_db()
        paid_on = date(y + m // 12, m % 12 + 1, 2)
        if paid_on <= today:
            run.mark_paid(paid_on)
