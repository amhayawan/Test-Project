"""Supply-chain defaults. Approval limits are PLACEHOLDERS until the board sets them."""
from decimal import Decimal

from core.seeding import policy

POLICIES = [
    ("supply.request", Decimal(0), ["finance_manager"]),
    ("supply.request", Decimal(50000), ["finance_manager", "executive"]),
    ("supply.order", Decimal(0), ["finance_manager"]),
    ("supply.order", Decimal(100000), ["finance_manager", "executive"]),
    ("supply.invoice", Decimal(0), ["finance_manager"]),
]

# (code, Arabic, English, stock account code or None, expense account code or None)
CATEGORIES = [
    ("RELIEF", "مواد إغاثة وكراتين غذائية", "Relief goods and food boxes", "1120", "5102"),
    ("MED", "مستلزمات طبية", "Medical supplies", "1120", "5103"),
    ("OFFICE", "أدوات مكتبية ومطبوعات", "Office supplies and printing", "1121", "5303"),
    ("SERV", "خدمات وصيانة", "Services and maintenance", None, "5306"),
    ("EQUIP", "أجهزة ومعدات", "Equipment", None, None),
]


def run(stdout):
    from finance.models import Account

    from .models import ItemCategory, Warehouse
    for args in POLICIES:
        policy(*args)
    Warehouse.objects.get_or_create(code="MAIN", defaults={"name_ar": "المخزن الرئيسي", "name_en": "Main store"})
    for code, ar, en, stock, expense in CATEGORIES:
        ItemCategory.objects.get_or_create(code=code, defaults={
            "name_ar": ar, "name_en": en,
            "inventory_account": Account.objects.filter(code=stock).first() if stock else None,
            "expense_account": Account.objects.filter(code=expense).first() if expense else None})
