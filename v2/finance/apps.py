from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class FinanceConfig(AppConfig):
    name = "finance"
    verbose_name = _("Finance and accounting")

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from approvals.registry import register as register_doc
        from core.audit import track
        from core.events import business_event

        from . import builders, posting
        from . import models as m

        register_doc("finance.journal", _("Journal entry"))
        register_doc("finance.payment", _("Payment voucher"))
        for model in (m.Account, m.AccountMapping, m.FiscalYear, m.JournalEntry, m.Payment, m.AssetCategory,
                      m.FixedAsset):
            track(model)

        posting.register("donation.received", builders.donation)
        posting.register("aid.delivered", builders.aid)
        posting.register("payroll.approved", builders.payroll_approved)
        posting.register("payroll.paid", builders.payroll_paid)
        posting.register("payment.paid", builders.payment)
        business_event.connect(posting.on_business_event, weak=False, dispatch_uid="finance-events")

        # donations are booked as soon as they are recorded, and re-booked if corrected or deleted
        from crm.models import Donation

        def donation_saved(sender, instance, raw=False, **kw):
            if not raw:
                posting.handle("donation.received", instance)

        def donation_deleted(sender, instance, **kw):
            entry = posting.live_entry(instance, "donation.received")
            if entry:
                posting.reverse(entry)

        post_save.connect(donation_saved, sender=Donation, weak=False, dispatch_uid="finance-donation-saved")
        post_delete.connect(donation_deleted, sender=Donation, weak=False, dispatch_uid="finance-donation-deleted")
