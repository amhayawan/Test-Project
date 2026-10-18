"""Supply chain: suppliers, items, stores, purchase requests and orders, goods receipts, supplier
invoices (3-way match), stock issues and the stock ledger.

Controls built in:
* purchase requests, purchase orders and supplier invoices go through maker-checker approval;
* whoever raised the purchase order cannot confirm receipt of the goods;
* an invoice cannot charge more quantity than was received, nor a higher price than ordered;
* nothing can be issued beyond what is on hand.

Stock is valued at moving-average cost: the stock ledger keeps quantity and value per item and
store, and an issue takes value ÷ quantity. Every movement is booked in finance automatically
(through business events), so the stock accounts always equal the stock ledger.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BilingualName, Department, Fund, Project, next_number

CENT = Decimal("0.01")
QTY = Decimal("0.001")
ZERO = Decimal(0)


def money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def num(value):
    """6.000 -> '6', 2.500 -> '2.5' for messages."""
    return format(Decimal(value or 0).normalize(), "f")


class SupplyError(Exception):
    pass


# ---------------------------------------------------------------- master data

class Supplier(models.Model):
    code = models.CharField(_("code"), max_length=20, unique=True)
    name = models.CharField(_("name"), max_length=160)
    tax_no = models.CharField(_("tax registration no."), max_length=40, blank=True)
    commercial_register = models.CharField(_("commercial register no."), max_length=40, blank=True)
    contact_person = models.CharField(_("contact person"), max_length=120, blank=True)
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    email = models.EmailField(_("email"), blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    bank_account = models.CharField(_("bank account / IBAN"), max_length=60, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("supplier")
        verbose_name_plural = _("suppliers")
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} {self.name}"


class ItemCategory(BilingualName):
    code = models.CharField(_("code"), max_length=20, unique=True)
    inventory_account = models.ForeignKey("finance.Account", verbose_name=_("stock account"), null=True, blank=True,
                                          related_name="+", on_delete=models.PROTECT,
                                          help_text=_("Empty = the posting rule 'supply.inventory'."))
    expense_account = models.ForeignKey("finance.Account", verbose_name=_("expense account"), null=True, blank=True,
                                        related_name="+", on_delete=models.PROTECT,
                                        help_text=_("Empty = the posting rule 'supply.expense'."))

    class Meta:
        verbose_name = _("item category")
        verbose_name_plural = _("item categories")
        ordering = ["code"]


class Item(BilingualName):
    STOCK, NON_STOCK, ASSET = "stock", "non_stock", "asset"
    KINDS = [(STOCK, _("Kept in the store")), (NON_STOCK, _("Service / used at once (expense)")),
             (ASSET, _("Fixed asset"))]

    code = models.CharField(_("code"), max_length=30, unique=True)
    category = models.ForeignKey(ItemCategory, verbose_name=_("category"), on_delete=models.PROTECT)
    kind = models.CharField(_("kind"), max_length=10, choices=KINDS, default=STOCK)
    unit = models.CharField(_("unit"), max_length=20, default="piece")
    asset_category = models.ForeignKey("finance.AssetCategory", verbose_name=_("asset category"), null=True,
                                       blank=True, on_delete=models.PROTECT)
    reorder_level = models.DecimalField(_("reorder level"), max_digits=12, decimal_places=3, default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("item")
        verbose_name_plural = _("items")
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def clean(self):
        if self.kind == self.ASSET and not self.asset_category_id:
            raise ValidationError({"asset_category": _("Choose the asset category for a fixed-asset item.")})


class Warehouse(BilingualName):
    code = models.CharField(_("code"), max_length=20, unique=True)
    location = models.CharField(_("location"), max_length=160, blank=True)
    keeper = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("storekeeper"), null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("store")
        verbose_name_plural = _("stores")
        ordering = ["code"]


class StockMove(models.Model):
    """The stock ledger. Positive quantity = into the store, negative = out. Quantity 0 = value correction."""

    item = models.ForeignKey(Item, verbose_name=_("item"), related_name="moves", on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, verbose_name=_("store"), related_name="moves", on_delete=models.PROTECT)
    date = models.DateField(_("date"))
    qty = models.DecimalField(_("quantity"), max_digits=14, decimal_places=3)
    value = models.DecimalField(_("value (EGP)"), max_digits=14, decimal_places=2)
    source_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    source_id = models.PositiveBigIntegerField()
    source_document = GenericForeignKey("source_type", "source_id")
    memo = models.CharField(_("memo"), max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["item", "warehouse"])]

    def __str__(self):
        return f"{self.item.code} {self.qty:+}"

    @property
    def unit_cost(self):
        return money(self.value / self.qty) if self.qty else ZERO


def on_hand(item, warehouse):
    """(quantity, value) of one item in one store."""
    t = StockMove.objects.filter(item=item, warehouse=warehouse).aggregate(q=Sum("qty"), v=Sum("value"))
    return t["q"] or ZERO, t["v"] or ZERO


def average_cost(item, warehouse):
    qty, value = on_hand(item, warehouse)
    return value / qty if qty > 0 else ZERO


# ---------------------------------------------------------------- shared helpers

class ApprovalDocument(models.Model):
    """Common status handling for documents that go through the approval engine."""

    DRAFT, PENDING, APPROVED, REJECTED, RETURNED = "draft", "pending", "approved", "rejected", "returned"

    class Meta:
        abstract = True

    def _set(self, status):
        type(self).objects.filter(pk=self.pk).update(status=status)
        self.status = status

    def on_approval_submitted(self, request):
        self.check_ready()
        self._set(self.PENDING)

    def on_approval_approved(self, request):
        self._set(self.APPROVED)

    def on_approval_rejected(self, request):
        self._set(self.REJECTED)

    def on_approval_returned(self, request):
        self._set(self.RETURNED)

    def on_approval_cancelled(self, request):
        self._set(self.DRAFT)

    def check_ready(self):
        if not self.lines.exists():
            raise ValidationError(_("Add at least one line."))

    @property
    def editable(self):
        return self.status in (self.DRAFT, self.RETURNED)


def lines_total(lines, price_field):
    return money(sum((l.qty * getattr(l, price_field) for l in lines), ZERO))


# ---------------------------------------------------------------- purchase request

class PurchaseRequest(ApprovalDocument):
    ORDERED, CLOSED = "ordered", "closed"
    STATUSES = [(ApprovalDocument.DRAFT, _("Draft")), (ApprovalDocument.PENDING, _("Awaiting approval")),
                (ApprovalDocument.APPROVED, _("Approved")), (ApprovalDocument.RETURNED, _("Returned for changes")),
                (ApprovalDocument.REJECTED, _("Rejected")), (ORDERED, _("Ordered")), (CLOSED, _("Closed"))]

    request_no = models.CharField(_("request no."), max_length=20, unique=True, editable=False)
    date = models.DateField(_("date"), default=timezone.localdate)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("requested by"), null=True,
                                  editable=False, related_name="+", on_delete=models.SET_NULL)
    department = models.ForeignKey(Department, verbose_name=_("department / cost centre"), on_delete=models.PROTECT)
    project = models.ForeignKey(Project, verbose_name=_("project"), null=True, blank=True, on_delete=models.PROTECT)
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)
    needed_by = models.DateField(_("needed by"), null=True, blank=True)
    purpose = models.CharField(_("purpose"), max_length=255)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=ApprovalDocument.DRAFT,
                              editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("purchase request")
        verbose_name_plural = _("purchase requests")
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.request_no} {self.purpose}"

    def save(self, *args, **kwargs):
        if not self.request_no:
            self.request_no = next_number("purchase_request", self.date.year)
        super().save(*args, **kwargs)

    def clean(self):
        if self.project_id and self.department_id and self.project.department_id != self.department_id:
            raise ValidationError({"project": _("The project belongs to another department.")})

    @property
    def total(self):
        return lines_total(self.lines.all(), "estimated_price")

    approval_doc_type = "supply.request"

    def approval_title(self):
        return f"{self.request_no} — {self.purpose}"

    def approval_amount(self):
        return self.total

    def ordered_qty(self, item, exclude_order=None):
        qs = PurchaseOrderLine.objects.filter(order__request=self, item=item).exclude(
            order__status__in=(PurchaseOrder.REJECTED,))
        if exclude_order is not None:
            qs = qs.exclude(order=exclude_order)
        return qs.aggregate(s=Sum("qty"))["s"] or ZERO


class PurchaseRequestLine(models.Model):
    request = models.ForeignKey(PurchaseRequest, related_name="lines", on_delete=models.CASCADE)
    item = models.ForeignKey(Item, verbose_name=_("item"), on_delete=models.PROTECT)
    description = models.CharField(_("specification"), max_length=255, blank=True)
    qty = models.DecimalField(_("quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(QTY)])
    estimated_price = models.DecimalField(_("estimated unit price"), max_digits=12, decimal_places=2,
                                          validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = _("purchase request line")
        verbose_name_plural = _("purchase request lines")

    def __str__(self):
        return f"{self.item} × {self.qty}"


# ---------------------------------------------------------------- purchase order

class PurchaseOrder(ApprovalDocument):
    RECEIVED, CLOSED = "received", "closed"
    STATUSES = [(ApprovalDocument.DRAFT, _("Draft")), (ApprovalDocument.PENDING, _("Awaiting approval")),
                (ApprovalDocument.APPROVED, _("Approved – sent to supplier")),
                (ApprovalDocument.RETURNED, _("Returned for changes")), (ApprovalDocument.REJECTED, _("Rejected")),
                (RECEIVED, _("Fully received")), (CLOSED, _("Closed"))]

    order_no = models.CharField(_("order no."), max_length=20, unique=True, editable=False)
    request = models.ForeignKey(PurchaseRequest, verbose_name=_("purchase request"), related_name="orders",
                                on_delete=models.PROTECT, limit_choices_to={"status__in": ("approved", "ordered")})
    supplier = models.ForeignKey(Supplier, verbose_name=_("supplier"), related_name="orders", on_delete=models.PROTECT)
    date = models.DateField(_("date"), default=timezone.localdate)
    expected_on = models.DateField(_("expected delivery"), null=True, blank=True)
    terms = models.CharField(_("payment and delivery terms"), max_length=255, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=ApprovalDocument.DRAFT,
                              editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, editable=False, related_name="+",
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("purchase order")
        verbose_name_plural = _("purchase orders")
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.order_no} {self.supplier.name}"

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = next_number("purchase_order", self.date.year)
        super().save(*args, **kwargs)

    def clean(self):
        if self.request_id and self.request.status not in (PurchaseRequest.APPROVED, PurchaseRequest.ORDERED):
            raise ValidationError({"request": _("The purchase request is not approved.")})
        if self.supplier_id and not self.supplier.is_active:
            raise ValidationError({"supplier": _("This supplier is not active.")})

    @property
    def total(self):
        return lines_total(self.lines.all(), "unit_price")

    def check_ready(self):
        super().check_ready()
        if self.request.status not in (PurchaseRequest.APPROVED, PurchaseRequest.ORDERED):
            raise ValidationError(_("The purchase request is not approved."))
        requested = {}
        for line in self.request.lines.all():
            requested[line.item_id] = requested.get(line.item_id, ZERO) + line.qty
        for line in self.lines.select_related("item"):
            if line.item_id not in requested:
                raise ValidationError(_("%(item)s was not in the purchase request.") % {"item": line.item})
            already = self.request.ordered_qty(line.item, exclude_order=self)
            if already + line.qty > requested[line.item_id]:
                raise ValidationError(_("%(item)s: ordering %(q)s but only %(left)s left on the request.")
                                      % {"item": line.item, "q": num(line.qty), "left": num(requested[line.item_id] - already)})

    approval_doc_type = "supply.order"

    def approval_title(self):
        return f"{self.order_no} — {self.supplier.name}"

    def approval_amount(self):
        return self.total

    def on_approval_approved(self, request):
        super().on_approval_approved(request)
        PurchaseRequest.objects.filter(pk=self.request_id, status=PurchaseRequest.APPROVED) \
            .update(status=PurchaseRequest.ORDERED)

    def received_qty(self, item, exclude_receipt=None):
        qs = GoodsReceiptLine.objects.filter(receipt__purchase_order=self, receipt__status=GoodsReceipt.CONFIRMED,
                                             item=item)
        if exclude_receipt is not None:
            qs = qs.exclude(receipt=exclude_receipt)
        return qs.aggregate(s=Sum("qty"))["s"] or ZERO

    def invoiced_qty(self, item, exclude_invoice=None):
        qs = SupplierInvoiceLine.objects.filter(invoice__purchase_order=self, item=item).exclude(
            invoice__status=SupplierInvoice.REJECTED)
        if exclude_invoice is not None:
            qs = qs.exclude(invoice=exclude_invoice)
        return qs.aggregate(s=Sum("qty"))["s"] or ZERO

    def ordered(self):
        """{item_id: (qty, unit price)} for this order."""
        out = {}
        for line in self.lines.all():
            q, _p = out.get(line.item_id, (ZERO, line.unit_price))
            out[line.item_id] = (q + line.qty, line.unit_price)
        return out

    def refresh_received(self):
        if all(self.received_qty(line.item) >= line.qty for line in self.lines.all()):
            self._set(self.RECEIVED)


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, related_name="lines", on_delete=models.CASCADE)
    item = models.ForeignKey(Item, verbose_name=_("item"), on_delete=models.PROTECT)
    qty = models.DecimalField(_("quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(QTY)])
    unit_price = models.DecimalField(_("agreed unit price"), max_digits=12, decimal_places=2,
                                     validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = _("purchase order line")
        verbose_name_plural = _("purchase order lines")
        unique_together = [("order", "item")]

    def __str__(self):
        return f"{self.item} × {self.qty}"


# ---------------------------------------------------------------- goods receipt

class GoodsReceipt(models.Model):
    DRAFT, CONFIRMED = "draft", "confirmed"
    STATUSES = [(DRAFT, _("Draft")), (CONFIRMED, _("Confirmed – in stock"))]

    receipt_no = models.CharField(_("receipt no."), max_length=20, unique=True, editable=False)
    date = models.DateField(_("date received"), default=timezone.localdate)
    warehouse = models.ForeignKey(Warehouse, verbose_name=_("store"), on_delete=models.PROTECT)
    purchase_order = models.ForeignKey(PurchaseOrder, verbose_name=_("purchase order"), null=True, blank=True,
                                       related_name="receipts", on_delete=models.PROTECT)
    donation = models.ForeignKey("crm.Donation", verbose_name=_("in-kind donation"), null=True, blank=True,
                                 related_name="goods_receipts", on_delete=models.PROTECT)
    delivery_note = models.CharField(_("supplier delivery note no."), max_length=60, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=DRAFT, editable=False)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("received by"), null=True,
                                    editable=False, related_name="+", on_delete=models.SET_NULL)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("goods receipt")
        verbose_name_plural = _("goods receipts")
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.receipt_no

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            self.receipt_no = next_number("goods_receipt", self.date.year)
        super().save(*args, **kwargs)

    def clean(self):
        if bool(self.purchase_order_id) == bool(self.donation_id):
            raise ValidationError(_("Choose either a purchase order or an in-kind donation."))
        if self.purchase_order_id and self.purchase_order.status != PurchaseOrder.APPROVED:
            raise ValidationError({"purchase_order": _("Goods can only be received against an approved order.")})
        if self.donation_id and self.donation.method != "in_kind":
            raise ValidationError({"donation": _("This donation is not an in-kind donation.")})

    @property
    def total(self):
        return lines_total(self.lines.all(), "unit_cost")

    @transaction.atomic
    def confirm(self, user):
        from core.events import emit
        receipt = GoodsReceipt.objects.select_for_update().get(pk=self.pk)
        if receipt.status != self.DRAFT:
            raise SupplyError(_("This receipt is already confirmed."))
        self.full_clean()
        lines = list(self.lines.select_related("item"))
        if not lines:
            raise SupplyError(_("Add at least one line."))
        po = self.purchase_order
        if po is not None:
            if user is not None and po.created_by_id == user.pk:
                raise SupplyError(_("You raised this purchase order, so someone else must confirm receiving the goods."))
            ordered = po.ordered()
            for line in lines:
                if line.item_id not in ordered:
                    raise SupplyError(_("%(item)s is not on the purchase order.") % {"item": line.item})
                qty, price = ordered[line.item_id]
                left = qty - po.received_qty(line.item, exclude_receipt=self)
                if line.qty > left:
                    raise SupplyError(_("%(item)s: receiving %(q)s but only %(left)s still to come.")
                                      % {"item": line.item, "q": num(line.qty), "left": num(left)})
                if line.unit_cost != price:
                    GoodsReceiptLine.objects.filter(pk=line.pk).update(unit_cost=price)
                    line.unit_cost = price
        else:
            if any(line.item.kind != Item.STOCK for line in lines):
                raise SupplyError(_("In-kind donations received into the store must be stock items."))
            if self.total != money(self.donation.amount):
                raise SupplyError(_("The goods are valued at %(t)s but the donation receipt says %(d)s.")
                                  % {"t": self.total, "d": self.donation.amount})
            if self.donation.goods_receipts.filter(status=self.CONFIRMED).exclude(pk=self.pk).exists():
                raise SupplyError(_("Goods for this donation were already received."))
        ct = ContentType.objects.get_for_model(self)
        for line in lines:
            if line.item.kind == Item.STOCK:
                StockMove.objects.create(item=line.item, warehouse=self.warehouse, date=self.date, qty=line.qty,
                                         value=money(line.qty * line.unit_cost), source_type=ct, source_id=self.pk,
                                         memo=self.receipt_no)
        GoodsReceipt.objects.filter(pk=self.pk).update(status=self.CONFIRMED, received_by=user,
                                                       confirmed_at=timezone.now())
        self.status, self.received_by = self.CONFIRMED, user
        if po is not None:
            po.refresh_received()
        emit("supply.receipt", self)
        return self


class GoodsReceiptLine(models.Model):
    receipt = models.ForeignKey(GoodsReceipt, related_name="lines", on_delete=models.CASCADE)
    item = models.ForeignKey(Item, verbose_name=_("item"), on_delete=models.PROTECT)
    qty = models.DecimalField(_("quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(QTY)])
    unit_cost = models.DecimalField(_("unit value"), max_digits=12, decimal_places=2, default=0,
                                    validators=[MinValueValidator(0)],
                                    help_text=_("Purchase orders: taken from the order. In-kind: the agreed value."))

    class Meta:
        verbose_name = _("goods receipt line")
        verbose_name_plural = _("goods receipt lines")

    def __str__(self):
        return f"{self.item} × {self.qty}"


# ---------------------------------------------------------------- supplier invoice

class SupplierInvoice(ApprovalDocument):
    PAID = "paid"
    STATUSES = [(ApprovalDocument.DRAFT, _("Draft")), (ApprovalDocument.PENDING, _("Awaiting approval")),
                (ApprovalDocument.APPROVED, _("Approved – to be paid")),
                (ApprovalDocument.RETURNED, _("Returned for changes")), (ApprovalDocument.REJECTED, _("Rejected")),
                (PAID, _("Paid"))]

    invoice_no = models.CharField(_("our reference"), max_length=20, unique=True, editable=False)
    supplier_ref = models.CharField(_("supplier's invoice no."), max_length=60)
    purchase_order = models.ForeignKey(PurchaseOrder, verbose_name=_("purchase order"), related_name="invoices",
                                       on_delete=models.PROTECT)
    date = models.DateField(_("invoice date"), default=timezone.localdate)
    due_date = models.DateField(_("due date"), null=True, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=ApprovalDocument.DRAFT,
                              editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, editable=False, related_name="+",
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("supplier invoice")
        verbose_name_plural = _("supplier invoices")
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.invoice_no} {self.supplier.name} ({self.supplier_ref})"

    @property
    def supplier(self):
        return self.purchase_order.supplier

    def save(self, *args, **kwargs):
        if not self.invoice_no:
            self.invoice_no = next_number("supplier_invoice", self.date.year)
        super().save(*args, **kwargs)

    def clean(self):
        if self.purchase_order_id and self.purchase_order.status not in (PurchaseOrder.APPROVED, PurchaseOrder.RECEIVED,
                                                                        PurchaseOrder.CLOSED):
            raise ValidationError({"purchase_order": _("The purchase order is not approved.")})
        if self.supplier_ref and self.purchase_order_id and SupplierInvoice.objects.filter(
                purchase_order__supplier=self.purchase_order.supplier, supplier_ref=self.supplier_ref) \
                .exclude(pk=self.pk).exclude(status=self.REJECTED).exists():
            raise ValidationError({"supplier_ref": _("This supplier invoice number was already recorded.")})

    @property
    def total(self):
        return lines_total(self.lines.all(), "unit_price")

    def check_ready(self):
        """3-way match: order ↔ goods received ↔ invoice."""
        super().check_ready()
        po = self.purchase_order
        ordered = po.ordered()
        for line in self.lines.select_related("item"):
            if line.item_id not in ordered:
                raise ValidationError(_("%(item)s is not on the purchase order.") % {"item": line.item})
            _qty, price = ordered[line.item_id]
            if line.unit_price > price:
                raise ValidationError(_("%(item)s: invoiced at %(p)s, higher than the agreed price %(o)s.")
                                      % {"item": line.item, "p": line.unit_price, "o": price})
            received = po.received_qty(line.item)
            invoiced = po.invoiced_qty(line.item, exclude_invoice=self)
            if invoiced + line.qty > received:
                raise ValidationError(_("%(item)s: invoiced %(q)s but only %(r)s received and not yet invoiced.")
                                      % {"item": line.item, "q": num(line.qty), "r": num(received - invoiced)})

    approval_doc_type = "supply.invoice"

    def approval_title(self):
        return f"{self.invoice_no} — {self.supplier.name} ({self.supplier_ref})"

    def approval_amount(self):
        return self.total

    def on_approval_approved(self, request):
        from core.events import emit
        super().on_approval_approved(request)
        emit("supply.invoice", self)
        self._apply_price_differences()

    def _apply_price_differences(self):
        """Invoiced below the order price: the stock ledger keeps the lower real cost."""
        po = self.purchase_order
        ordered = po.ordered()
        ct = ContentType.objects.get_for_model(self)
        receipt = po.receipts.filter(status=GoodsReceipt.CONFIRMED).order_by("-date").first()
        for line in self.lines.select_related("item"):
            diff = money(line.qty * (ordered[line.item_id][1] - line.unit_price))
            if diff and line.item.kind == Item.STOCK and receipt is not None:
                StockMove.objects.create(item=line.item, warehouse=receipt.warehouse, date=self.date, qty=ZERO,
                                         value=-diff, source_type=ct, source_id=self.pk,
                                         memo=_("Price lower than ordered"))

    # finance.Payment pays it through its generic link
    def amount_to_pay(self, exclude=None):
        from finance.models import Payment
        qs = Payment.objects.filter(for_type=ContentType.objects.get_for_model(self), for_id=self.pk,
                                    status__in=(Payment.PENDING, Payment.APPROVED, Payment.PAID))
        if exclude is not None and exclude.pk:
            qs = qs.exclude(pk=exclude.pk)
        return self.total - (qs.aggregate(s=Sum("amount"))["s"] or ZERO)

    def paid_amount(self):
        from finance.models import Payment
        return Payment.objects.filter(for_type=ContentType.objects.get_for_model(self), for_id=self.pk,
                                      status=Payment.PAID).aggregate(s=Sum("amount"))["s"] or ZERO

    def on_paid(self, payment):
        if self.paid_amount() >= self.total:
            self._set(self.PAID)


class SupplierInvoiceLine(models.Model):
    invoice = models.ForeignKey(SupplierInvoice, related_name="lines", on_delete=models.CASCADE)
    item = models.ForeignKey(Item, verbose_name=_("item"), on_delete=models.PROTECT)
    qty = models.DecimalField(_("quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(QTY)])
    unit_price = models.DecimalField(_("unit price"), max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = _("supplier invoice line")
        verbose_name_plural = _("supplier invoice lines")

    def __str__(self):
        return f"{self.item} × {self.qty}"


# ---------------------------------------------------------------- stock issue

class StockIssue(models.Model):
    PROJECT, DEPARTMENT, AID = "project", "department", "aid"
    PURPOSES = [(PROJECT, _("Project / programme")), (DEPARTMENT, _("Department use")),
                (AID, _("Aid to a case (approved aid)"))]
    DRAFT, CONFIRMED = "draft", "confirmed"
    STATUSES = [(DRAFT, _("Draft")), (CONFIRMED, _("Issued"))]

    issue_no = models.CharField(_("issue no."), max_length=20, unique=True, editable=False)
    date = models.DateField(_("date"), default=timezone.localdate)
    warehouse = models.ForeignKey(Warehouse, verbose_name=_("store"), on_delete=models.PROTECT)
    purpose = models.CharField(_("issued for"), max_length=12, choices=PURPOSES, default=PROJECT)
    project = models.ForeignKey(Project, verbose_name=_("project"), null=True, blank=True, on_delete=models.PROTECT)
    department = models.ForeignKey(Department, verbose_name=_("department / cost centre"), null=True, blank=True,
                                   on_delete=models.PROTECT)
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)
    aid = models.OneToOneField("cases.Aid", verbose_name=_("aid"), null=True, blank=True, related_name="stock_issue",
                               on_delete=models.PROTECT)
    received_by_name = models.CharField(_("handed to"), max_length=160, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=DRAFT, editable=False)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, editable=False, related_name="+",
                                  on_delete=models.SET_NULL)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("stock issue")
        verbose_name_plural = _("stock issues")
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.issue_no

    def save(self, *args, **kwargs):
        if not self.issue_no:
            self.issue_no = next_number("stock_issue", self.date.year)
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if self.purpose == self.AID:
            if not self.aid_id:
                errors["aid"] = _("Choose the approved aid these goods are given for.")
            elif self.aid.status != self.aid.APPROVED or self.aid.paid_by != "stock":
                errors["aid"] = _("The aid must be approved and marked as goods from the store.")
        elif self.purpose == self.PROJECT and not self.project_id:
            errors["project"] = _("Choose the project.")
        elif self.purpose == self.DEPARTMENT and not self.department_id:
            errors["department"] = _("Choose the department.")
        if errors:
            raise ValidationError(errors)

    @property
    def total(self):
        return money(sum((l.value for l in self.lines.all()), ZERO))

    @transaction.atomic
    def confirm(self, user):
        from core.events import emit
        issue = StockIssue.objects.select_for_update().get(pk=self.pk)
        if issue.status != self.DRAFT:
            raise SupplyError(_("This issue is already confirmed."))
        self.full_clean()
        lines = list(self.lines.select_related("item"))
        if not lines:
            raise SupplyError(_("Add at least one line."))
        ct = ContentType.objects.get_for_model(self)
        needed = {}
        for line in lines:
            if line.item.kind != Item.STOCK:
                raise SupplyError(_("%(item)s is not kept in the store.") % {"item": line.item})
            needed[line.item_id] = needed.get(line.item_id, ZERO) + line.qty
        for line in lines:
            qty, _value = on_hand(line.item, self.warehouse)
            if needed[line.item_id] > qty:
                raise SupplyError(_("%(item)s: %(q)s requested but only %(h)s in %(w)s.")
                                  % {"item": line.item, "q": num(needed[line.item_id]), "h": num(qty), "w": self.warehouse})
        for line in lines:
            qty, value = on_hand(line.item, self.warehouse)
            out = money(value) if line.qty == qty else money(value / qty * line.qty)
            StockMove.objects.create(item=line.item, warehouse=self.warehouse, date=self.date, qty=-line.qty,
                                     value=-out, source_type=ct, source_id=self.pk, memo=self.issue_no)
            StockIssueLine.objects.filter(pk=line.pk).update(value=out)
        StockIssue.objects.filter(pk=self.pk).update(status=self.CONFIRMED, issued_by=user, confirmed_at=timezone.now())
        self.status, self.issued_by = self.CONFIRMED, user
        emit("supply.issue", self)
        if self.aid_id:
            self.aid.mark_delivered(self.date)
        return self


class StockIssueLine(models.Model):
    issue = models.ForeignKey(StockIssue, related_name="lines", on_delete=models.CASCADE)
    item = models.ForeignKey(Item, verbose_name=_("item"), on_delete=models.PROTECT)
    qty = models.DecimalField(_("quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(QTY)])
    value = models.DecimalField(_("value at cost"), max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = _("stock issue line")
        verbose_name_plural = _("stock issue lines")

    def __str__(self):
        return f"{self.item} × {self.qty}"

