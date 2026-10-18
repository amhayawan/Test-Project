"""Demo supply chain: suppliers, items, a full purchase cycle, goods for aid cases and projects,
an in-kind donation received into the store, and documents waiting at each step."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from approvals import services
from crm.models import Donation
from finance.models import AssetCategory, Payment, mapped

from .models import (GoodsReceipt, GoodsReceiptLine, Item, ItemCategory, PurchaseOrder, PurchaseOrderLine,
                     PurchaseRequest, PurchaseRequestLine, StockIssue, StockIssueLine, Supplier, SupplierInvoice,
                     SupplierInvoiceLine, Warehouse)

D = Decimal


def approve(doc, maker, approvers, stop_after=None):
    """Send for approval and approve step by step (stop_after=n leaves it waiting after n decisions)."""
    req = services.submit(doc, maker)
    for n, user in enumerate(approvers):
        if stop_after is not None and n >= stop_after:
            break
        req.refresh_from_db()
        if req.status != req.PENDING:
            break
        if services.can_act(req, user):
            services.decide(req, user, "approve")
    doc.refresh_from_db()
    return doc


def run(ctx):
    today, u = ctx.today, ctx.u
    chain = [u["finmanager"], u["director"]]
    store = Warehouse.objects.get(code="MAIN")
    Warehouse.objects.filter(pk=store.pk).update(keeper=u["storekeeper"])
    cat = {c.code: c for c in ItemCategory.objects.all()}
    sup = [Supplier.objects.create(code=code, name=name, phone=phone, tax_no=tax) for code, name, phone, tax in (
        ("S-001", "شركة الخير للمواد الغذائية", "0223456789", "100-200-300"),
        ("S-002", "الشركة المصرية للمستلزمات الطبية", "0227654321", "100-200-301"),
        ("S-003", "مكتبة النور للأدوات المكتبية", "0221122334", "100-200-302"),
        ("S-004", "شركة التقنية الحديثة", "0224455667", "100-200-303"))]
    item = {
        "box": Item.objects.create(code="FBOX", name_ar="كرتونة مواد غذائية", category=cat["RELIEF"], unit="carton",
                                   reorder_level=D(50)),
        "blanket": Item.objects.create(code="BLNK", name_ar="بطانية شتوية", category=cat["RELIEF"], reorder_level=D(30)),
        "medkit": Item.objects.create(code="MKIT", name_ar="حقيبة إسعافات أولية", category=cat["MED"], reorder_level=D(20)),
        "paper": Item.objects.create(code="A4", name_ar="ورق تصوير A4", category=cat["OFFICE"], unit="ream",
                                     reorder_level=D(20)),
        "clean": Item.objects.create(code="CLN", name_ar="خدمة نظافة شهرية", category=cat["SERV"], kind=Item.NON_STOCK),
        "laptop": Item.objects.create(code="LTP", name_ar="حاسب محمول", category=cat["EQUIP"], kind=Item.ASSET,
                                      asset_category=AssetCategory.objects.get(code="IT")),
    }

    def purchase(day, requester, dept, project, fund, purpose, lines, supplier, receive=True, invoice=True, pay=True,
                 invoice_waits=False):
        pr = PurchaseRequest.objects.create(date=day, requester=requester, department=ctx.dept[dept], project=project,
                                            fund=fund, purpose=purpose, needed_by=day + timedelta(days=14))
        for it, qty, est in lines:
            PurchaseRequestLine.objects.create(request=pr, item=it, qty=D(qty), estimated_price=D(est))
        approve(pr, requester, chain)
        po = PurchaseOrder.objects.create(request=pr, supplier=supplier, created_by=u["procurement"],
                                          date=day + timedelta(days=2), expected_on=day + timedelta(days=9))
        for it, qty, est in lines:
            PurchaseOrderLine.objects.create(order=po, item=it, qty=D(qty), unit_price=D(est) * D("0.96"))
        approve(po, u["procurement"], chain)
        if not receive:
            return po
        grn = GoodsReceipt.objects.create(warehouse=store, purchase_order=po, date=day + timedelta(days=8),
                                          delivery_note=f"DN-{po.order_no[-4:]}")
        for it, qty, _est in lines:
            GoodsReceiptLine.objects.create(receipt=grn, item=it, qty=D(qty))
        grn.confirm(u["storekeeper"])
        if not invoice:
            return po
        inv = SupplierInvoice.objects.create(purchase_order=po, supplier_ref=f"INV-{po.order_no[-4:]}",
                                             date=day + timedelta(days=10), due_date=day + timedelta(days=40),
                                             created_by=u["accountant"])
        for line in po.lines.all():
            SupplierInvoiceLine.objects.create(invoice=inv, item=line.item, qty=line.qty, unit_price=line.unit_price)
        approve(inv, u["accountant"], chain, stop_after=0 if invoice_waits else None)
        if not pay or invoice_waits:
            return po
        p = Payment.objects.create(payee=supplier.name, amount=inv.amount_to_pay(), method="bank",
                                   debit_account=mapped("supply.payable"), fund=pr.fund, project=pr.project,
                                   department=pr.department, prepared_by=u["accountant"], date=day + timedelta(days=20),
                                   description=f"{inv.invoice_no} ({inv.supplier_ref})",
                                   for_type=ContentType.objects.get_for_model(inv), for_id=inv.pk)
        approve(p, u["accountant"], chain)
        p.mark_paid(day + timedelta(days=20))
        return po

    d0 = today - timedelta(days=100)
    purchase(d0, u["pm"], "PRG", ctx.project["FOOD"], ctx.fund["GEN"], "كراتين غذائية لمشروع الإطعام",
             [(item["box"], 400, 250)], sup[0])
    purchase(d0 + timedelta(days=5), u["projects"], "PRG", ctx.project["MED"], ctx.fund["MED"],
             "حقائب إسعافات للقافلة الطبية", [(item["medkit"], 60, 400)], sup[1])
    purchase(d0 + timedelta(days=10), u["hrmanager"], "ADM", None, ctx.fund["GEN"], "أجهزة ومستلزمات للمكتب",
             [(item["laptop"], 2, 22000), (item["paper"], 40, 180), (item["clean"], 1, 3000)], sup[3])
    # documents waiting at each step
    purchase(today - timedelta(days=12), u["projects"], "PRG", ctx.project["MED"], ctx.fund["MED"],
             "حقائب إسعافات إضافية", [(item["medkit"], 30, 400)], sup[1], invoice_waits=True)
    purchase(today - timedelta(days=6), u["pm"], "PRG", ctx.project["FOOD"], ctx.fund["GEN"], "كراتين إضافية",
             [(item["box"], 150, 250)], sup[0], receive=False)
    waiting = PurchaseRequest.objects.create(date=today - timedelta(days=1), requester=u["hrmanager"],
                                             department=ctx.dept["ADM"], fund=ctx.fund["GEN"], purpose="ورق تصوير")
    PurchaseRequestLine.objects.create(request=waiting, item=item["paper"], qty=D(30), estimated_price=D(180))
    services.submit(waiting, u["hrmanager"])

    # in-kind donation of blankets received into the store at its value
    donor = next(d for d in ctx.donors if d.donor_type == d.COMPANY)
    gift = Donation.objects.create(donor=donor, amount=D(15000), method="in_kind", purpose="general",
                                   donation_date=today - timedelta(days=40), fund=ctx.fund["GEN"],
                                   recorded_by=u["fundraiser"], notes="300 بطانية")
    grn = GoodsReceipt.objects.create(warehouse=store, donation=gift, date=today - timedelta(days=40))
    GoodsReceiptLine.objects.create(receipt=grn, item=item["blanket"], qty=D(300), unit_cost=D(50))
    grn.confirm(u["storekeeper"])

    # goods out: approved food aid to cases, and distribution for the projects
    for aid in getattr(ctx, "stock_aids", []):
        issue = StockIssue.objects.create(warehouse=store, purpose=StockIssue.AID, aid=aid,
                                          date=today - timedelta(days=30), received_by_name=aid.beneficiary.name)
        StockIssueLine.objects.create(issue=issue, item=item["box"], qty=D(3))
        issue.confirm(u["storekeeper"])
    for qty, days, it, project, fund in ((300, 60, "box", "FOOD", "GEN"), (180, 45, "blanket", "FOOD", "GEN"),
                                         (45, 50, "medkit", "MED", "MED")):
        issue = StockIssue.objects.create(warehouse=store, purpose=StockIssue.PROJECT, project=ctx.project[project],
                                          fund=ctx.fund[fund], date=today - timedelta(days=days),
                                          received_by_name="فريق التوزيع الميداني")
        StockIssueLine.objects.create(issue=issue, item=item[it], qty=D(qty))
        issue.confirm(u["storekeeper"])
