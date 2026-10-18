"""Supply chain: request → order → receipt → invoice (3-way match) → payment, in-kind goods, stock issues."""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import translation

from approvals import services
from cases.models import Aid, Beneficiary
from crm.models import Donation, Donor
from finance import posting, reports
from finance.models import Account, AssetCategory, Payment, mapped
from supply.models import (GoodsReceipt, GoodsReceiptLine, Item, ItemCategory, PurchaseOrder, PurchaseOrderLine,
                           PurchaseRequest, PurchaseRequestLine, StockIssue, StockIssueLine, StockMove, Supplier,
                           SupplierInvoice, SupplierInvoiceLine, SupplyError, Warehouse, on_hand)
from test_hr import org  # noqa: F401

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


def bal(code, as_of=None):
    return reports.balance_of([Account.objects.get(code=code)], as_of)


@pytest.fixture
def sc(org, make_user):
    org.update(fm=make_user("fm", "finance_manager"), accountant=make_user("acct", "accountant"),
               buyer=make_user("buyer", "procurement_officer"), keeper=make_user("keeper", "storekeeper"),
               requester=make_user("req", "case_manager"))
    org["store"] = Warehouse.objects.get(code="MAIN")
    org["supplier"] = Supplier.objects.create(code="S1", name="شركة التوريدات")
    org["rice"] = Item.objects.create(code="RICE", name_ar="أرز 5 كجم", category=ItemCategory.objects.get(code="RELIEF"),
                                      unit="bag", reorder_level=D(3))
    org["service"] = Item.objects.create(code="CLEAN", name_ar="خدمة نظافة", kind=Item.NON_STOCK,
                                         category=ItemCategory.objects.get(code="SERV"))
    org["laptop"] = Item.objects.create(code="LAP", name_ar="لابتوب", kind=Item.ASSET,
                                        category=ItemCategory.objects.get(code="EQUIP"),
                                        asset_category=AssetCategory.objects.get(code="IT"))
    return org


def approve(doc, maker, *approvers):
    req = services.submit(doc, maker)
    for user in approvers:
        services.decide(req, user, "approve")
    doc.refresh_from_db()
    return doc


def ordered_and_received(sc):
    pr = PurchaseRequest.objects.create(department=sc["prog"], purpose="مستلزمات رمضان", requester=sc["requester"],
                                        date=date(2026, 3, 1))
    for item, qty, price in ((sc["rice"], 10, 100), (sc["service"], 1, 500), (sc["laptop"], 1, 20000)):
        PurchaseRequestLine.objects.create(request=pr, item=item, qty=D(qty), estimated_price=D(price))
    approve(pr, sc["requester"], sc["fm"])
    assert pr.status == PurchaseRequest.APPROVED

    po = PurchaseOrder.objects.create(request=pr, supplier=sc["supplier"], created_by=sc["buyer"], date=date(2026, 3, 2))
    PurchaseOrderLine.objects.create(order=po, item=sc["rice"], qty=D(11), unit_price=D(95))
    with pytest.raises(ValidationError, match="only 10"):
        services.submit(po, sc["buyer"])                      # more than requested
    PurchaseOrderLine.objects.filter(order=po).update(qty=D(10))
    PurchaseOrderLine.objects.create(order=po, item=sc["service"], qty=D(1), unit_price=D(500))
    PurchaseOrderLine.objects.create(order=po, item=sc["laptop"], qty=D(1), unit_price=D(20000))
    approve(po, sc["buyer"], sc["fm"])
    pr.refresh_from_db()
    assert po.status == PurchaseOrder.APPROVED and pr.status == PurchaseRequest.ORDERED

    grn = GoodsReceipt.objects.create(warehouse=sc["store"], purchase_order=po, date=date(2026, 3, 5))
    for item, qty in ((sc["rice"], 6), (sc["service"], 1), (sc["laptop"], 1)):
        GoodsReceiptLine.objects.create(receipt=grn, item=item, qty=D(qty))
    with pytest.raises(SupplyError, match="someone else"):
        grn.confirm(sc["buyer"])                              # whoever ordered cannot receive
    grn.confirm(sc["keeper"])
    return pr, po, grn


def test_purchase_to_payment_chain(sc):
    pr, po, grn = ordered_and_received(sc)
    assert on_hand(sc["rice"], sc["store"]) == (D(6), D(570))
    assert bal("1120") == D(570) and bal("2102") == D(-570)

    inv = SupplierInvoice.objects.create(purchase_order=po, supplier_ref="INV-77", created_by=sc["accountant"],
                                         date=date(2026, 3, 6))
    line = SupplierInvoiceLine.objects.create(invoice=inv, item=sc["rice"], qty=D(10), unit_price=D(90))
    with pytest.raises(ValidationError, match="only 6 received"):
        services.submit(inv, sc["accountant"])
    line.qty, line.unit_price = D(6), D(99)
    line.save()
    with pytest.raises(ValidationError, match="higher than the agreed price"):
        services.submit(inv, sc["accountant"])
    line.unit_price = D(90)
    line.save()
    SupplierInvoiceLine.objects.create(invoice=inv, item=sc["service"], qty=D(1), unit_price=D(500))
    SupplierInvoiceLine.objects.create(invoice=inv, item=sc["laptop"], qty=D(1), unit_price=D(20000))
    approve(inv, sc["accountant"], sc["fm"])
    assert inv.status == SupplierInvoice.APPROVED and inv.total == D(21040)

    entry = posting.live_entry(inv, "supply.invoice")
    # Dr clearing 570 + service 500 + laptop 20,000 = Cr supplier 21,040 + stock price difference 30
    assert entry.totals() == (D(21070), D(21070))
    assert bal("2102") == 0                                   # goods-received clearing account cleared
    assert bal("1120") == D(540) and on_hand(sc["rice"], sc["store"])[1] == D(540)   # stock ledger = GL
    assert bal("5306") == D(500) and bal("1204") == D(20000) and bal("2101") == D(-21040)

    p = Payment.objects.create(payee=inv.supplier.name, amount=D(30000), debit_account=mapped("supply.payable"),
                               description=inv.invoice_no, prepared_by=sc["accountant"], date=date(2026, 3, 10),
                               for_type=ContentType.objects.get_for_model(inv), for_id=inv.pk)
    with pytest.raises(ValidationError, match="still owed"):
        p.full_clean()
    p.amount = inv.amount_to_pay()
    p.save()
    approve(p, sc["accountant"], sc["fm"])
    p.mark_paid()
    inv.refresh_from_db()
    assert inv.status == SupplierInvoice.PAID and bal("2101") == 0 and bal("1102") == D(-21040)
    assert reports.balance_sheet(date(2026, 12, 31))["check"] == 0


def test_payment_voucher_admin_action(sc):
    _pr, po, _grn = ordered_and_received(sc)
    inv = SupplierInvoice.objects.create(purchase_order=po, supplier_ref="X1", created_by=sc["accountant"])
    SupplierInvoiceLine.objects.create(invoice=inv, item=sc["rice"], qty=D(6), unit_price=D(95))
    approve(inv, sc["accountant"], sc["fm"])
    c = Client()
    c.force_login(sc["accountant"])
    sc["accountant"].is_staff = True
    sc["accountant"].save()
    r = c.post("/backoffice/supply/supplierinvoice/", {"action": "create_payment", "_selected_action": [inv.pk]})
    assert r.status_code == 302
    p = Payment.objects.get()
    assert p.amount == D(570) and p.for_document == inv and p.debit_account == mapped("supply.payable")


def test_in_kind_donation_goes_into_stock(sc):
    blankets = Item.objects.create(code="BLK", name_ar="بطانية", category=ItemCategory.objects.get(code="RELIEF"))
    d = Donation.objects.create(donor=Donor.objects.create(name="متبرع"), amount=D(1000), method="in_kind",
                                donation_date=date(2026, 3, 3))
    grn = GoodsReceipt.objects.create(warehouse=sc["store"], donation=d, date=date(2026, 3, 3))
    line = GoodsReceiptLine.objects.create(receipt=grn, item=blankets, qty=D(20), unit_cost=D(40))
    with pytest.raises(SupplyError, match="donation receipt says"):
        grn.confirm(sc["keeper"])
    line.unit_cost = D(50)
    line.save()
    grn.confirm(sc["keeper"])
    assert on_hand(blankets, sc["store"]) == (D(20), D(1000))
    assert bal("1120") == D(1000) and bal("4107") == D(-1000)
    with pytest.raises(ValidationError):
        GoodsReceipt(warehouse=sc["store"]).full_clean()          # needs an order or a donation


def test_stock_issue_to_aid_case_books_expense_once(sc):
    ordered_and_received(sc)                                      # 6 bags of rice at 95
    case = Beneficiary.objects.create(name="حالة", status=Beneficiary.APPROVED)
    aid = Aid.objects.create(beneficiary=case, aid_type="food", value=D(400), paid_by="stock", status=Aid.APPROVED)
    issue = StockIssue.objects.create(warehouse=sc["store"], purpose=StockIssue.AID, aid=aid, date=date(2026, 3, 8))
    StockIssueLine.objects.create(issue=issue, item=sc["rice"], qty=D(4))
    issue.confirm(sc["keeper"])
    aid.refresh_from_db()
    assert aid.status == Aid.DELIVERED
    assert bal("5102") == D(380)                                  # 4 × 95, booked once (not again by aid delivery)
    assert on_hand(sc["rice"], sc["store"]) == (D(2), D(190)) and bal("1120") == D(190)

    over = StockIssue.objects.create(warehouse=sc["store"], purpose=StockIssue.DEPARTMENT, department=sc["prog"])
    StockIssueLine.objects.create(issue=over, item=sc["rice"], qty=D(5))
    with pytest.raises(SupplyError, match="only 2"):
        over.confirm(sc["keeper"])
    assert StockMove.objects.filter(source_id=over.pk, qty__lt=0).count() == 0

    cash_aid = Aid.objects.create(beneficiary=case, aid_type="food", value=D(100), paid_by="cash", status=Aid.APPROVED)
    with pytest.raises(ValidationError, match="goods from the store"):
        StockIssue(warehouse=sc["store"], purpose=StockIssue.AID, aid=cash_aid).full_clean()
    assert reports.balance_sheet(date(2026, 12, 31))["check"] == 0


def test_pages_and_dashboard(sc):
    ordered_and_received(sc)
    c = Client()
    c.force_login(sc["keeper"])
    page = c.get("/supply/stock/").content.decode()
    assert "RICE" in page and "570.00" in page
    assert sc["keeper"].has_perm("supply.add_goodsreceipt") and not sc["keeper"].has_perm("supply.add_purchaseorder")
    c.force_login(sc["executive"])
    assert c.get("/").status_code == 200
    c.force_login(sc["hr_officer"])
    assert c.get("/supply/stock/").status_code == 403


def test_missing_posting_rule_does_not_block_the_store(sc):
    from finance.models import AccountMapping, PostingIssue
    AccountMapping.objects.filter(key="supply.received_not_invoiced").delete()
    _pr, po, grn = ordered_and_received(sc)
    assert grn.status == GoodsReceipt.CONFIRMED and on_hand(sc["rice"], sc["store"])[0] == D(6)
    assert PostingIssue.objects.filter(event="supply.receipt", resolved_at__isnull=True).exists()
