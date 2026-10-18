from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand

from approvals.models import ApprovalPolicy, ApprovalStep
from core.models import Fund

FUNDS = [
    ("GEN", "الصندوق العام", "General fund", Fund.UNRESTRICTED),
    ("ZAK", "صندوق الزكاة", "Zakat fund", Fund.ZAKAT),
    ("ORPH", "صندوق كفالة الأيتام", "Orphan sponsorship fund", Fund.RESTRICTED),
]

# Leave types: names and structure only. NO day counts or limits are seeded: HR enters them from
# the labour law / internal policy and the labour-law specialist signs them off before use.
# (code, Arabic, English, extra settings)
LEAVE_TYPES = [
    ("ANNUAL", "إجازة اعتيادية (سنوية)", "Annual leave", {}),
    ("CASUAL", "إجازة عارضة", "Casual leave", {"deduct_from": "ANNUAL"}),
    ("SICK", "إجازة مرضية", "Sick leave", {"needs_document": True}),
    ("MATERNITY", "إجازة وضع", "Maternity leave", {"gender": "f", "needs_document": True}),
    ("PATERNITY", "إجازة أبوة", "Paternity leave", {"gender": "m"}),
    ("HAJJ", "إجازة حج / عمرة", "Hajj / pilgrimage leave", {}),
    ("EXAM", "إجازة امتحانات", "Exam leave", {"needs_document": True}),
    ("UNPAID", "إجازة بدون أجر", "Unpaid leave", {"paid_percent": Decimal(0)}),
    ("PERMIT", "إذن (ساعات)", "Permission (hours)", {"unit": "hours"}),
    ("MISSION", "مأمورية", "Mission (work outside the office)", {"nature": "duty"}),
]

# (document type, from amount, [approver roles in order]). Edit later in the back office.
POLICIES = [
    ("cases.case", Decimal(0), ["case_manager"]),
    ("cases.aid", Decimal(0), ["case_manager"]),
    ("cases.aid", Decimal(10000), ["case_manager", "executive"]),
    ("hr.incentive", Decimal(0), ["hr_manager"]),
    ("hr.incentive", Decimal(5000), ["hr_manager", "executive"]),
    ("hr.payroll", Decimal(0), ["hr_manager", "executive"]),
    ("hr.leave", Decimal(0), ["line_manager"]),
]


class Command(BaseCommand):
    help = "Create roles, default funds and default approval policies (safe to run again)."

    def handle(self, *args, **options):
        call_command("setup_roles", stdout=self.stdout)
        for code, ar, en, kind in FUNDS:
            Fund.objects.get_or_create(code=code, defaults={"name_ar": ar, "name_en": en, "kind": kind})
        for doc_type, min_amount, roles in POLICIES:
            policy, created = ApprovalPolicy.objects.get_or_create(doc_type=doc_type, min_amount=min_amount)
            if created:
                for order, role in enumerate(roles, start=1):
                    ApprovalStep.objects.create(policy=policy, order=order, role=Group.objects.get(name=role))
        from hr.models import LeaveType
        for code, ar, en, extra in LEAVE_TYPES:
            extra = dict(extra)
            if "deduct_from" in extra:
                extra["deduct_from"] = LeaveType.objects.get(code=extra["deduct_from"])
            LeaveType.objects.get_or_create(code=code, defaults={"name_ar": ar, "name_en": en, **extra})
        self.stdout.write(self.style.SUCCESS("Defaults ready."))
