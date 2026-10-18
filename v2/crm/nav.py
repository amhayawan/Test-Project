"""Menu entries for this module: (label, url, permission needed)."""
from django.utils.translation import gettext_lazy as _

GROUP = _("Donor management")
ITEMS = [
    (_("Donors"), "/backoffice/crm/donor/", "crm.view_donor"),
    (_("Donations"), "/backoffice/crm/donation/", "crm.view_donation"),
    (_("Campaigns"), "/backoffice/crm/campaign/", "crm.view_campaign"),
    (_("Sponsorships"), "/backoffice/crm/sponsorship/", "crm.view_sponsorship"),
]
