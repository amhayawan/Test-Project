"""Demo logins: one per role (password in core/management/commands/load_demo.py)."""
from django.contrib.auth.models import Group

from .models import User

# username, Arabic name, English name, roles, superuser
LOGINS = [
    ("admin", "مدير النظام", "System administrator", ["admin"], True),
    ("director", "د. سامية فؤاد", "Dr. Samia Fouad", ["executive"], False),
    ("casemanager", "منى عبد الحميد", "Mona Abdelhamid", ["case_manager"], False),       # Research Dept manager
    ("projects", "شريف منير", "Sherif Mounir", ["projects_officer"], False),             # Projects Dept officer
    ("researcher1", "أحمد سعيد", "Ahmed Saeed", ["researcher"], False),
    ("researcher2", "هبة محمود", "Heba Mahmoud", ["researcher"], False),
    ("fundraiser", "كريم يوسف", "Karim Youssef", ["fundraising"], False),
    ("hrmanager", "نادية حسن", "Nadia Hassan", ["hr_manager"], False),
    ("hrofficer", "ياسمين علي", "Yasmine Ali", ["hr_officer"], False),
    ("payroll", "طارق فهمي", "Tarek Fahmy", ["payroll_officer"], False),
    ("sara", "سارة إبراهيم", "Sara Ibrahim", ["labour_specialist"], False),
    ("finmanager", "حسام الدين رشاد", "Hossam Rashad", ["finance_manager"], False),
    ("accountant", "مروة شوقي", "Marwa Shawky", ["accountant"], False),
    ("procurement", "عمرو جلال", "Amr Galal", ["procurement_officer"], False),
    ("storekeeper", "محمد عبد الله", "Mohamed Abdallah", ["storekeeper"], False),
    ("pm", "رانيا عادل", "Rania Adel", ["project_manager"], False),            # Projects Dept manager
]


def run(ctx):
    for username, ar, en, roles, superuser in LOGINS:
        user = User.objects.create_user(username, f"{username}@demo.invalid", ctx.password, name_ar=ar, name_en=en,
                                        is_superuser=superuser, is_staff=True, language="ar")
        user.groups.set(Group.objects.filter(name__in=roles))
        ctx.users[username] = (", ".join(roles), User.objects.get(pk=user.pk))
    ctx.u = {k: v[1] for k, v in ctx.users.items()}
