from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from approvals import services
from core.admin import AttachmentInline, stamp_attachments

from . import assets, posting
from .models import (Account, AccountMapping, AssetCategory, DepreciationRun, FinanceError, FiscalYear, FixedAsset,
                     JournalEntry, JournalLine, Payment, PostingIssue)


def _error(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


@admin.action(description=_("Send for approval"))
def send_for_approval(modeladmin, request, queryset):
    for obj in queryset:
        try:
            services.submit(obj, request.user)
            modeladmin.message_user(request, f"{obj}: ✓", messages.SUCCESS)
        except (services.ApprovalError, ValidationError, FinanceError) as exc:
            modeladmin.message_user(request, f"{obj}: {_error(exc)}", messages.ERROR)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "name_en", "kind", "parent", "postable", "contra", "is_active")
    list_filter = ("kind", "postable", "is_active")
    search_fields = ("code", "name_ar", "name_en")
    ordering = ("code",)


@admin.register(AccountMapping)
class AccountMappingAdmin(admin.ModelAdmin):
    list_display = ("key", "account", "description")
    search_fields = ("key", "description")
    autocomplete_fields = ("account",)


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ("year", "locked_through", "closed")


class LineInline(admin.TabularInline):
    model = JournalLine
    extra = 2
    autocomplete_fields = ("account",)
    fields = ("account", "debit", "credit", "fund", "project", "department", "memo")

    def has_change_permission(self, request, obj=None):
        return (obj is None or obj.status in (JournalEntry.DRAFT, JournalEntry.RETURNED)) and \
            super().has_change_permission(request, obj)

    has_add_permission = has_delete_permission = has_change_permission


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("entry_no", "date", "description", "source", "status", "debit_total", "created_by")
    list_filter = ("status", "source", "date")
    search_fields = ("entry_no", "description", "lines__memo")
    date_hierarchy = "date"
    readonly_fields = ("entry_no", "status", "source_event", "reverses", "created_by", "posted_at")
    inlines = [LineInline, AttachmentInline]
    actions = [send_for_approval, "reverse_entries"]

    @admin.display(description=_("amount"))
    def debit_total(self, obj):
        return f"{obj.totals()[0]:,.2f}"

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status not in (JournalEntry.DRAFT, JournalEntry.RETURNED):
            fields += ["date", "description", "source"]
        return fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            obj.source = obj.source if obj.source in ("manual", "opening") else "manual"
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        if formset.model.__name__ == "Attachment":
            stamp_attachments(request, formset)
        else:
            formset.save()

    def has_delete_permission(self, request, obj=None):
        return (obj is None or obj.status in (JournalEntry.DRAFT, JournalEntry.RETURNED, JournalEntry.REJECTED)) \
            and super().has_delete_permission(request, obj)

    @admin.action(description=_("Reverse (creates a reversing entry for approval)"))
    def reverse_entries(self, request, queryset):
        for entry in queryset:
            try:
                rev = posting.reverse(entry, request.user, post=False)
                services.submit(rev, request.user)
                self.message_user(request, _("%(no)s: reversal %(rev)s sent for approval.")
                                  % {"no": entry.entry_no, "rev": rev.entry_no}, messages.SUCCESS)
            except (FinanceError, services.ApprovalError, ValidationError) as exc:
                self.message_user(request, f"{entry}: {_error(exc)}", messages.ERROR)


@admin.register(PostingIssue)
class PostingIssueAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event", "source_document", "message", "resolved_at")
    list_filter = ("event", ("resolved_at", admin.EmptyFieldListFilter))
    readonly_fields = ("event", "source_type", "source_id", "message", "extra", "created_at", "resolved_at")
    actions = ["retry"]

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Retry (after fixing the posting rule or the locked month)"))
    def retry(self, request, queryset):
        for issue in queryset.filter(resolved_at__isnull=True):
            ok = posting.retry(issue)
            self.message_user(request, f"{issue.event}: {'✓' if ok else issue.message}",
                              messages.SUCCESS if ok else messages.ERROR)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("payment_no", "date", "payee", "amount", "method", "debit_account", "status", "prepared_by")
    list_filter = ("status", "method")
    search_fields = ("payment_no", "payee", "reference", "description")
    autocomplete_fields = ("debit_account",)
    readonly_fields = ("payment_no", "status", "prepared_by", "for_document")
    inlines = [AttachmentInline]
    actions = [send_for_approval, "mark_paid"]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.prepared_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        stamp_attachments(request, formset)

    def has_change_permission(self, request, obj=None):
        return (obj is None or obj.status in (Payment.DRAFT, Payment.RETURNED)) and \
            super().has_change_permission(request, obj)

    @admin.action(description=_("Mark as paid (money has left: posts the entry)"))
    def mark_paid(self, request, queryset):
        for p in queryset:
            try:
                p.mark_paid()
                self.message_user(request, f"{p}: ✓", messages.SUCCESS)
            except FinanceError as exc:
                self.message_user(request, f"{p}: {exc}", messages.ERROR)


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "asset_account", "accumulated_account", "expense_account", "life_months")


@admin.register(FixedAsset)
class FixedAssetAdmin(admin.ModelAdmin):
    list_display = ("asset_no", "name", "category", "acquired_on", "cost", "book_value_now", "department", "location",
                    "custodian", "disposed_on")
    list_filter = ("category", "department", ("disposed_on", admin.EmptyFieldListFilter))
    search_fields = ("asset_no", "name", "serial", "location")
    autocomplete_fields = ("custodian",)
    readonly_fields = ("asset_no",)
    inlines = [AttachmentInline]

    @admin.display(description=_("book value"))
    def book_value_now(self, obj):
        return f"{obj.book_value():,.2f}"

    def save_formset(self, request, form, formset, change):
        stamp_attachments(request, formset)


@admin.register(DepreciationRun)
class DepreciationRunAdmin(admin.ModelAdmin):
    list_display = ("__str__", "total", "status", "entry")
    readonly_fields = ("total", "entry")
    actions = ["calculate"]

    @admin.action(description=_("Calculate and create the journal (then send it for approval)"))
    def calculate(self, request, queryset):
        for run in queryset:
            try:
                run = assets.calculate(run, request.user)
                self.message_user(request, f"{run}: {run.total:,.2f}", messages.SUCCESS)
            except FinanceError as exc:
                self.message_user(request, f"{run}: {exc}", messages.ERROR)
