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

# (document type, from amount, [approver roles in order]). Edit later in the back office.
POLICIES = [
    ("cases.case", Decimal(0), ["case_manager"]),
    ("cases.aid", Decimal(0), ["case_manager"]),
    ("cases.aid", Decimal(10000), ["case_manager", "executive"]),
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
        self.stdout.write(self.style.SUCCESS("Defaults ready."))
