"""Demo project budgets (approved), milestones and tasks."""
from datetime import timedelta
from decimal import Decimal

from approvals import services
from finance.models import Account

from .models import BudgetLine, Milestone, ProjectProfile, Task

BUDGETS = {
    "ORPH": ("كفالة 120 يتيماً ومتابعتهم دراسياً وصحياً", 120, "منحة مؤسسة الأمل (تجريبي)",
             [("5101", "كفالات نقدية شهرية", 450000), ("5104", "مستلزمات مدارس", 80000), ("5201", "رواتب الفريق", 380000)]),
    "FOOD": ("توزيع 3000 شنطة رمضان ووجبات إطعام", 3000, "",
             [("5102", "شنط غذائية", 520000), ("5108", "تعبئة وتغليف ونقل", 70000), ("5201", "رواتب الفريق", 260000)]),
    "MED": ("قوافل طبية وعمليات لغير القادرين", 400, "",
            [("5103", "عمليات وعلاج", 360000), ("5201", "رواتب الفريق", 180000)]),
}
TASKS = [("تحديد الحالات المستحقة", "done", 100, 3), ("التعاقد مع الموردين", "done", 100, 2),
         ("التوزيع / التنفيذ الميداني", "doing", 60, 5), ("تقرير المتابعة للمانحين", "todo", 0, 2)]


def run(ctx):
    today, u = ctx.today, ctx.u
    for key, (objectives, target, grant, lines) in BUDGETS.items():
        project = ctx.project[key]
        profile = ProjectProfile.objects.create(project=project, objectives=objectives, target_beneficiaries=target,
                                                location="القاهرة الكبرى", grant_reference=grant)
        for code, desc, amount in lines:
            BudgetLine.objects.create(profile=profile, account=Account.objects.get(code=code), description=desc,
                                      amount=Decimal(amount), fund=project.fund)
        maker = project.manager or u["pm"]
        req = services.submit(profile, maker)
        services.decide(req, u["finmanager"], "approve")
        req.refresh_from_db()
        if req.status == req.PENDING:
            services.decide(req, u["director"], "approve")
        m1 = Milestone.objects.create(project=project, title="المرحلة الأولى: الإعداد", due=today - timedelta(days=120))
        m2 = Milestone.objects.create(project=project, title="المرحلة الثانية: التنفيذ", due=today + timedelta(days=45))
        for i, (title, status, pct, weight) in enumerate(TASKS):
            Task.objects.create(project=project, milestone=m1 if i < 2 else m2, title=title, assignee=maker,
                                start=today - timedelta(days=200 - i * 40), due=today + timedelta(days=-150 + i * 70),
                                status=status, percent=pct, weight=weight)
