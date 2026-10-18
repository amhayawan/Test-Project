from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from approvals import services
from core.admin import AttachmentInline, stamp_attachments

from django.urls import reverse
from django.utils.html import format_html

from .models import Aid, Beneficiary, CaseNeed, FamilyMember, HouseholdItem, MedicalCondition


class FamilyInline(admin.TabularInline):
    model = FamilyMember
    extra = 0
    fields = ("name", "relation", "age", "education", "education_work", "monthly_income", "job_stability",
              "not_working_reason", "able_to_work", "national_id", "gender", "health")


class MedicalInline(admin.TabularInline):
    model = MedicalCondition
    extra = 0


class HouseholdInline(admin.TabularInline):
    """The fixed appliances / furniture checklist of the research form."""
    model = HouseholdItem
    extra = 0
    max_num = 0
    can_delete = False
    fields = ("item", "present", "count", "condition")
    readonly_fields = ("item",)


class NeedInline(admin.TabularInline):
    model = CaseNeed
    extra = 0
    fields = ("need_type", "description", "amount_needed", "frequency", "priority", "is_open", "collected")
    readonly_fields = ("collected",)

    @admin.display(description=_("collected?"))
    def collected(self, obj):
        # researchers may ask whether the amount is collected, never who gave or how much
        return obj.funding_label if obj.pk else ""


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
    list_display = ("case_no", "name", "national_id", "category", "area", "researcher", "status", "assessment",
                    "referred_at")
    list_filter = ("status", "category", "assessment", "researcher", ("referred_at", admin.EmptyFieldListFilter))
    search_fields = ("case_no", "name", "national_id", "phone", "area")
    readonly_fields = ("case_no", "status", "referred_at", "income_total", "expenses_total", "gap", "print_form")
    inlines = [FamilyInline, MedicalInline, HouseholdInline, NeedInline, AttachmentInline]
    actions = [submit_for_approval]
    fieldsets = [
        (_("Case"), {"fields": ("case_no", "status", "referred_at", "print_form", "form_no", "visit_date",
                                "researcher", "category", "department", "project")}),
        (_("Head of the family"), {"fields": ("name", "national_id", "phone", "area", "address", "marital_status",
                                              "family_size")}),
        (_("Engaged daughter"), {"classes": ("collapse",), "fields": (
            "has_engaged_daughter", "engaged_daughter_name", "wedding_date", "marriage_needs_provided",
            "marriage_needs_remaining")}),
        (_("Income sources (monthly)"), {"fields": (
            "income_salaries", "income_takaful", "income_insurance", "income_charities", "income_benefactors",
            "benefactors_who", "income_total")}),
        (_("Expenses"), {"fields": (
            "exp_food_daily", "exp_rent", "exp_transport", "exp_education", "exp_installments", "exp_electricity",
            "exp_water", "exp_phone", "exp_gas", "expenses_total", "gap", "debts")}),
        (_("Housing"), {"fields": (
            "housing_type", "rooms", "house_area", "bathroom", "floor_type", "building_material", "water_connection",
            "water_distance", "needs_roof", "roof_room_area", "housing_condition", "other_appliances")}),
        (_("Other circumstances"), {"fields": (
            "ration_card_members", "no_ration_card_reason", "livestock", "livestock_count", "livestock_owner",
            "extra_burdens", "smoker", "health_summary")}),
        (_("Family needs"), {"fields": (
            "need_medical", "need_marriage", "need_project", "need_appliances", "need_monthly", "need_other")}),
        (_("Researcher's opinion"), {"fields": (
            "assessment", "research_findings", "recommendation", "zakat_eligible", "next_review_date", "notes")}),
    ]

    @admin.display(description=_("total income"))
    def income_total(self, obj):
        return f"{obj.total_income:,.2f}"

    @admin.display(description=_("total monthly expenses"))
    def expenses_total(self, obj):
        return f"{obj.total_expenses:,.2f}"

    @admin.display(description=_("monthly gap (expenses − income)"))
    def gap(self, obj):
        return f"{obj.monthly_gap:,.2f}"

    @admin.display(description=_("research form"))
    def print_form(self, obj):
        if not obj.pk:
            return ""
        return format_html('<a href="{}" target="_blank">🖶 {}</a>', reverse("research_form", args=[obj.pk]),
                           _("Print the research form"))

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
