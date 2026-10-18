from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = _("Organisation")

    def ready(self):
        from . import audit  # noqa: F401  (connects audit signals)
