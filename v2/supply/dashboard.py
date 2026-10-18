"""Supply-chain section of the dashboard (procurement, stores, finance and management)."""
from django.utils.translation import gettext_lazy as _

from dashboards.widgets import bar_rows

from .models import ZERO, PurchaseOrder, PurchaseRequest, SupplierInvoice
from .views import balances


def supply(user, f):
    if not (user.has_perm("supply.view_purchaseorder") or user.has_perm("supply.view_stockmove")):
        return None
    from finance import reports
    from finance.models import FinanceError, mapped
    try:
        grni = -reports.balance_of([mapped("supply.received_not_invoiced")], f.end)
        payable = -reports.balance_of([mapped("supply.payable")], f.end)
    except FinanceError:
        grni = payable = ZERO
    rows = balances()
    by_category = {}
    for r in rows:
        by_category[r["item"].category.name] = by_category.get(r["item"].category.name, ZERO) + r["value"]
    return {
        "kpis": [
            {"label": _("Purchase requests waiting"), "value": PurchaseRequest.objects.filter(
                status=PurchaseRequest.PENDING).count()},
            {"label": _("Open purchase orders"), "value": PurchaseOrder.objects.filter(
                status__in=(PurchaseOrder.PENDING, PurchaseOrder.APPROVED)).count()},
            {"label": _("Orders placed in period"), "value": PurchaseOrder.objects.filter(
                date__range=(f.start, f.end)).exclude(status__in=(PurchaseOrder.DRAFT, PurchaseOrder.REJECTED)).count()},
            {"label": _("Goods received, not yet invoiced"), "value": grni, "money": True},
            {"label": _("Invoices waiting for approval"), "value": SupplierInvoice.objects.filter(
                status=SupplierInvoice.PENDING).count()},
            {"label": _("Owed to suppliers"), "value": payable, "money": True},
            {"label": _("Stock value"), "value": sum((r["value"] for r in rows), ZERO), "money": True},
            {"label": _("Items at or below reorder level"), "value": sum(1 for r in rows if r["low"])},
        ],
        "by_category": bar_rows(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "low": [r for r in rows if r["low"]][:8],
    }


SECTIONS = [(supply, "supply/_dashboard.html")]
