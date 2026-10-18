from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CrmConfig(AppConfig):
    name = "crm"
    verbose_name = _("Donors and donations")

    def ready(self):
        from core.audit import track
        from .models import Campaign, Donation, Donor, Member, Sponsorship, Volunteer
        for model in (Donor, Campaign, Donation, Sponsorship, Volunteer, Member):
            track(model)
