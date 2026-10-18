from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ApprovalsConfig(AppConfig):
    name = "approvals"
    verbose_name = _("Approvals (maker-checker)")
