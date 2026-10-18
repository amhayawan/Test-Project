"""Menu entries for this module: (label, url, permission needed)."""
from django.utils.translation import gettext_lazy as _

GROUP = _("Finance")
ITEMS = [
    (_("Financial reports"), "/finance/", "finance.view_journalline"),
    (_("Journal entries"), "/backoffice/finance/journalentry/", "finance.view_journalentry"),
    (_("Payment vouchers"), "/backoffice/finance/payment/", "finance.view_payment"),
    (_("Fixed assets"), "/backoffice/finance/fixedasset/", "finance.view_fixedasset"),
    (_("Depreciation"), "/backoffice/finance/depreciationrun/", "finance.view_depreciationrun"),
    (_("Posting problems"), "/backoffice/finance/postingissue/", "finance.view_postingissue"),
    (_("Chart of accounts"), "/backoffice/finance/account/", "finance.view_account"),
    (_("Posting rules"), "/backoffice/finance/accountmapping/", "finance.view_accountmapping"),
    (_("Financial years and month-end lock"), "/backoffice/finance/fiscalyear/", "finance.view_fiscalyear"),
]
