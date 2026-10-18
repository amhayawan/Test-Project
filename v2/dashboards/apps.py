from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DashboardsConfig(AppConfig):
    name = "dashboards"
    verbose_name = _("Dashboards")
