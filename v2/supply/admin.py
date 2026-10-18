from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from approvals import services
from core.admin import AttachmentInline, stamp_attachments

from .models import (GoodsReceipt, GoodsReceiptLine, Item, ItemCategory, PurchaseOrder, PurchaseOrderLine,
                     PurchaseRequest, PurchaseRequestLine, StockIssue, StockIssueLine, StockMove, Supplier,
                     SupplierInvoice, SupplierInvoiceLine, SupplyError, Warehouse)


def _error(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


@admin.action(description=_("Send for approval"))
def send_for_approval(modeladmin, request, queryset):
    for obj in queryset:
        try:
            services.submit(obj, request.user)
            modeladmin.message_user(request, f"{obj}: ✓", messages.SUCCESS)
        except (services.ApprovalError, ValidationError) as exc:
            modeladmin.message_user(request, f"{obj}: {_error(exc)}", messages.ERROR)


class LockedAfterDraft:
    """Lines and header can only be changed while the document is a draft (or returned)."""

    def _editable(self, obj):
        if obj is None:
            return True
        return obj.status in ("draft", "returned")

    def has_change_permission(self, request, obj=None):
        return self._editable(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._editable(obj) and super().has_delete_permission(request, obj)


class LockedInline(LockedAfterDraft, admin.TabularInline):
    extra = 1
    autocomplete_fields = ("item",)

    def has_add_permission(self, request, obj=None):
        return self._editable(obj) and super().has_add_permission(request, obj)


class WithAttachments:
    def save_formset(self, request, form, formset, change):
        if formset.model.__name__ == "Attachment":
            stamp_attachments(request, formset)
        else:
            formset.save()


# ---------------------------------------------------------------- master data

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "contact_person", "phone", "tax_no", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "tax_no", "phone", "contact_person")


@admin.register(ItemCategory)
class ItemCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "name_en", "inventory_account", "expense_account")
    search_fields = ("code", "name_ar", "name_en")


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "category", "kind", "unit", "reorder_level", "is_active")
    list_filter = ("kind", "category", "is_active")
    search_fields = ("code", "name_ar", "name_en")


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "location", "keeper", "is_active")


@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ("date", "item", "warehouse", "qty", "value", "memo")
    list_filter = ("warehouse", "item__category", "date")
    search_fields = ("item__code", "item__name_ar", "memo")
    date_hierarchy = "date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------- purchasing

class RequestLineInline(LockedInline):
    model = PurchaseRequestLine


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(WithAttachments, LockedAfterDraft, admin.ModelAdmin):
    list_display = ("request_no", "date", "purpose", "department", "project", "requester", "total_display", "status")
    list_filter = ("status", "department", "project")
    search_fields = ("request_no", "purpose")
    readonly_fields = ("request_no", "requester", "status")
    inlines = [RequestLineInline, AttachmentInline]
    actions = [send_for_approval]

    @admin.display(description=_("estimated total"))
    def total_display(self, obj):
        return f"{obj.total:,.2f}"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.requester = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # people outside procurement / finance see only their own requests
        if request.user.has_perm("supply.view_purchaseorder") or request.user.is_superuser:
            return qs
        return qs.filter(requester=request.user)


class OrderLineInline(LockedInline):
    model = PurchaseOrderLine


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(WithAttachments, LockedAfterDraft, admin.ModelAdmin):
    list_display = ("order_no", "date", "supplier", "request", "total_display", "status", "created_by")
    list_filter = ("status", "supplier")
    search_fields = ("order_no", "supplier__name", "request__request_no")
    autocomplete_fields = ("supplier",)
    readonly_fields = ("order_no", "status", "created_by")
    inlines = [OrderLineInline, AttachmentInline]
    actions = [send_for_approval]

    @admin.display(description=_("total"))
    def total_display(self, obj):
        return f"{obj.total:,.2f}"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ReceiptLineInline(LockedInline):
    model = GoodsReceiptLine

    def _editable(self, obj):
        return obj is None or obj.status == GoodsReceipt.DRAFT


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(WithAttachments, LockedAfterDraft, admin.ModelAdmin):
    list_display = ("receipt_no", "date", "warehouse", "purchase_order", "donation", "status", "received_by")
    list_filter = ("status", "warehouse")
    search_fields = ("receipt_no", "purchase_order__order_no", "donation__receipt_no", "delivery_note")
    raw_id_fields = ("donation",)
    readonly_fields = ("receipt_no", "status", "received_by", "confirmed_at")
    inlines = [ReceiptLineInline, AttachmentInline]
    actions = ["confirm"]

    def _editable(self, obj):
        return obj is None or obj.status == GoodsReceipt.DRAFT

    @admin.action(description=_("Confirm goods received (adds to stock and books it)"))
    def confirm(self, request, queryset):
        for r in queryset:
            try:
                r.confirm(request.user)
                self.message_user(request, f"{r}: ✓", messages.SUCCESS)
            except (SupplyError, ValidationError) as exc:
                self.message_user(request, f"{r}: {_error(exc)}", messages.ERROR)


class InvoiceLineInline(LockedInline):
    model = SupplierInvoiceLine


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(WithAttachments, LockedAfterDraft, admin.ModelAdmin):
    list_display = ("invoice_no", "supplier_ref", "date", "purchase_order", "total_display", "outstanding", "status")
    list_filter = ("status",)
    search_fields = ("invoice_no", "supplier_ref", "purchase_order__order_no", "purchase_order__supplier__name")
    readonly_fields = ("invoice_no", "status", "created_by")
    inlines = [InvoiceLineInline, AttachmentInline]
    actions = [send_for_approval, "create_payment"]

    @admin.display(description=_("total"))
    def total_display(self, obj):
        return f"{obj.total:,.2f}"

    @admin.display(description=_("still to pay"))
    def outstanding(self, obj):
        return f"{obj.total - obj.paid_amount():,.2f}"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Create payment voucher for what is still owed"))
    def create_payment(self, request, queryset):
        from finance.models import FinanceError, Payment, mapped
        for inv in queryset:
            if inv.status != SupplierInvoice.APPROVED:
                self.message_user(request, _("%(i)s: only approved invoices can be paid.") % {"i": inv},
                                  messages.ERROR)
                continue
            amount = inv.amount_to_pay()
            if amount <= 0:
                self.message_user(request, _("%(i)s: a payment voucher already covers it.") % {"i": inv},
                                  messages.WARNING)
                continue
            try:
                req = inv.purchase_order.request
                p = Payment.objects.create(
                    payee=inv.supplier.name, amount=amount, method="bank", debit_account=mapped("supply.payable"),
                    fund=req.fund, project=req.project, department=req.department, prepared_by=request.user,
                    description=f"{inv.invoice_no} ({inv.supplier_ref})",
                    for_type=ContentType.objects.get_for_model(inv), for_id=inv.pk)
            except FinanceError as exc:
                self.message_user(request, f"{inv}: {exc}", messages.ERROR)
                continue
            self.message_user(request, _("%(i)s: payment voucher %(p)s created; send it for approval.")
                              % {"i": inv, "p": p.payment_no}, messages.SUCCESS)


# ---------------------------------------------------------------- stock issue

class IssueLineInline(LockedInline):
    model = StockIssueLine
    fields = ("item", "qty", "value")
    readonly_fields = ("value",)

    def _editable(self, obj):
        return obj is None or obj.status == StockIssue.DRAFT


@admin.register(StockIssue)
class StockIssueAdmin(WithAttachments, LockedAfterDraft, admin.ModelAdmin):
    list_display = ("issue_no", "date", "warehouse", "purpose", "project", "department", "aid", "status", "issued_by")
    list_filter = ("status", "purpose", "warehouse")
    search_fields = ("issue_no", "aid__aid_no", "received_by_name")
    raw_id_fields = ("aid",)
    readonly_fields = ("issue_no", "status", "issued_by", "confirmed_at")
    inlines = [IssueLineInline, AttachmentInline]
    actions = ["confirm"]

    def _editable(self, obj):
        return obj is None or obj.status == StockIssue.DRAFT

    @admin.action(description=_("Confirm issue (takes goods out of stock and books the cost)"))
    def confirm(self, request, queryset):
        for s in queryset:
            try:
                s.confirm(request.user)
                self.message_user(request, f"{s}: ✓", messages.SUCCESS)
            except (SupplyError, ValidationError) as exc:
                self.message_user(request, f"{s}: {_error(exc)}", messages.ERROR)
