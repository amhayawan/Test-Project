from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CasesConfig(AppConfig):
    name = "cases"
    verbose_name = _("Case management")

    def ready(self):
        from approvals.registry import register
        register("cases.case", _("Case acceptance"))
        register("cases.aid", _("Aid disbursement"))
        from core.audit import track
        from .models import Aid, Beneficiary, CaseNeed, FamilyMember
        for model in (Beneficiary, FamilyMember, CaseNeed, Aid):
            track(model)
