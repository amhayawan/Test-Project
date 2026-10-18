"""Menu entries for this module: (label, url, permission needed)."""
from django.utils.translation import gettext_lazy as _

GROUP = _("Supply chain")
ITEMS = [
    (_("Purchase requests"), "/backoffice/supply/purchaserequest/", "supply.view_purchaserequest"),
    (_("Purchase orders"), "/backoffice/supply/purchaseorder/", "supply.view_purchaseorder"),
    (_("Goods receipts"), "/backoffice/supply/goodsreceipt/", "supply.view_goodsreceipt"),
    (_("Supplier invoices"), "/backoffice/supply/supplierinvoice/", "supply.view_supplierinvoice"),
    (_("Stock issues"), "/backoffice/supply/stockissue/", "supply.view_stockissue"),
    (_("Stock on hand"), "/supply/stock/", "supply.view_stockmove"),
    (_("Suppliers"), "/backoffice/supply/supplier/", "supply.view_supplier"),
    (_("Items"), "/backoffice/supply/item/", "supply.view_item"),
    (_("Stores"), "/backoffice/supply/warehouse/", "supply.view_warehouse"),
]
