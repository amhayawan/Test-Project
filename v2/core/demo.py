"""Demo organisation: departments (cost centres), funds and projects."""
from datetime import date

from .models import Branch, Department, Fund, Project

DEPARTMENTS = [("ADM", "الإدارة العامة", "General administration"), ("PRG", "قسم المشروعات", "Projects Department"),
               ("RES", "قسم البحث الاجتماعي", "Social Research Department"),
               ("FR", "تنمية الموارد", "Fundraising"), ("FIN", "الشؤون المالية", "Finance"),
               ("HR", "الموارد البشرية", "Human resources"), ("SUP", "المشتريات والمخازن", "Procurement and stores")]


def run(ctx):
    Branch.objects.get_or_create(code="CAI", defaults={"name_ar": "الفرع الرئيسي – القاهرة", "name_en": "Main branch – Cairo"})
    ctx.dept = {code: Department.objects.get_or_create(code=code, defaults={"name_ar": ar, "name_en": en})[0]
                for code, ar, en in DEPARTMENTS}
    ctx.fund = {f.code: f for f in Fund.objects.all()}
    med = Fund.objects.get_or_create(code="MED", defaults={"name_ar": "صندوق العلاج", "name_en": "Medical fund",
                                                           "kind": Fund.RESTRICTED,
                                                           "restriction": "علاج المرضى غير القادرين فقط"})[0]
    ctx.fund["MED"] = med
    y = ctx.today.year
    ctx.project = {
        "ORPH": Project.objects.create(code=f"ORPH{y % 100}", name_ar="كفالة الأيتام", name_en="Orphan sponsorship",
                                       department=ctx.dept["PRG"], fund=ctx.fund["ORPH"], manager=ctx.u["pm"],
                                       start_date=date(y, 1, 1), end_date=date(y, 12, 31), status=Project.ACTIVE),
        "FOOD": Project.objects.create(code=f"RMD{y % 100}", name_ar="شنطة رمضان والإطعام", name_en="Ramadan food boxes",
                                       department=ctx.dept["PRG"], fund=ctx.fund["GEN"], manager=ctx.u["pm"],
                                       start_date=date(y, 2, 1), end_date=date(y, 12, 31), status=Project.ACTIVE),
        "MED": Project.objects.create(code=f"MED{y % 100}", name_ar="القوافل والعلاج", name_en="Medical aid and convoys",
                                      department=ctx.dept["PRG"], fund=med, manager=ctx.u["pm"],
                                      start_date=date(y, 1, 1), end_date=date(y, 12, 31), status=Project.ACTIVE),
    }
