from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SupplyConfig(AppConfig):
    name = "supply"
    verbose_name = _("Supply chain")

    def ready(self):
        from approvals.registry import register
        from core.audit import track
        from finance import posting

        from . import models as m
        from . import postings

        register("supply.request", _("Purchase request"))
        register("supply.order", _("Purchase order"))
        register("supply.invoice", _("Supplier invoice"))
        for model in (m.Supplier, m.ItemCategory, m.Item, m.Warehouse, m.PurchaseRequest, m.PurchaseRequestLine,
                      m.PurchaseOrder, m.PurchaseOrderLine, m.GoodsReceipt, m.GoodsReceiptLine, m.SupplierInvoice,
                      m.SupplierInvoiceLine, m.StockIssue, m.StockIssueLine, m.StockMove):
            track(model)
        posting.register("supply.receipt", postings.receipt)
        posting.register("supply.invoice", postings.invoice)
        posting.register("supply.issue", postings.issue)
