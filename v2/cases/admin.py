from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from approvals import services
from core.admin import AttachmentInline, stamp_attachments

from .models import Aid, Beneficiary, CaseNeed, FamilyMember


class FamilyInline(admin.TabularInline):
    model = FamilyMember
    extra = 0


class NeedInline(admin.TabularInline):
    model = CaseNeed
    extra = 0


def submit_for_approval(modeladmin, request, queryset):
    """Maker step: send the selected records into the approval workflow."""
    sent = 0
    for obj in queryset:
        try:
            services.submit(obj, request.user)
            sent += 1
        except (services.ApprovalError, ValidationError) as exc:
            msg = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            modeladmin.message_user(request, f"{obj}: {msg}", messages.ERROR)
    if sent:
        modeladmin.message_user(request, _("%(n)s sent for approval.") % {"n": sent}, messages.SUCCESS)


submit_for_approval.short_description = _("Send for approval")


@admin.register(Beneficiary)
class BeneficiaryAdmin(admin.ModelAdmin):
    list_display = ("case_no", "name", "national_id", "category", "area", "researcher", "status")
    list_filter = ("status", "category", "researcher")
    search_fields = ("case_no", "name", "national_id", "phone", "area")
    readonly_fields = ("case_no", "status")
    inlines = [FamilyInline, NeedInline, AttachmentInline]
    actions = [submit_for_approval]

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("cases.recommend_case"):
            actions.pop("submit_for_approval", None)
        return actions

    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj)
        return allowed and (obj is None or obj.can_edit_research(request.user))

    def get_queryset(self, request):
        return super().get_queryset(request).visible_to(request.user)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            if not request.user.has_perm("cases.view_all_cases"):
                obj.researcher = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        stamp_attachments(request, formset)


@admin.register(CaseNeed)
class CaseNeedAdmin(admin.ModelAdmin):
    list_display = ("beneficiary", "need_type", "description", "amount_needed", "priority", "is_open")
    search_fields = ("description", "beneficiary__name", "beneficiary__case_no")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            beneficiary__in=Beneficiary.objects.visible_to(request.user))


@admin.register(Aid)
class AidAdmin(admin.ModelAdmin):
    list_display = ("aid_no", "beneficiary", "aid_type", "value", "status", "delivered_on")
    list_filter = ("status", "aid_type")
    search_fields = ("aid_no", "beneficiary__name", "beneficiary__case_no")
    readonly_fields = ("aid_no", "status", "requested_by")
    autocomplete_fields = ("beneficiary", "need")
    actions = [submit_for_approval, "mark_delivered"]

    def has_change_permission(self, request, obj=None):
        # an aid request can only be edited before it is submitted or after it is returned
        allowed = super().has_change_permission(request, obj)
        return allowed and (obj is None or obj.status in (Aid.DRAFT, Aid.RETURNED))

    @admin.action(description=_("Mark as delivered (approved aid only)"))
    def mark_delivered(self, request, queryset):
        done = queryset.filter(status=Aid.APPROVED).exclude(paid_by="stock")
        for aid in done:
            aid.mark_delivered(timezone.localdate())
        skipped = queryset.count() - len(done)
        if skipped:
            self.message_user(request, _("%(n)s skipped: not approved.") % {"n": skipped}, messages.WARNING)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.requested_by = request.user
        super().save_model(request, obj, form, change)
