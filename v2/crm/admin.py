from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from cases.models import Beneficiary, CaseNeed
from core.admin import AttachmentInline, stamp_attachments

from .models import Campaign, Donation, Donor, Member, Sponsorship, Volunteer


class NeedByCode(forms.ModelChoiceField):
    def label_from_instance(self, need):
        # case code and need only: no names or personal details reach fundraising or donors
        return f"{need.beneficiary.case_no} · {need.get_need_type_display()} · {need.amount_needed:,.0f}"


class CaseCodeForm(forms.ModelForm):
    """Donors choose a case by its code; the person's identity stays with the research team."""

    case_code = forms.CharField(label=_("case code"), required=False, max_length=20,
                                help_text=_("e.g. C-2026-00012, as given to the donor"))
    need = NeedByCode(label=_("need"), required=False, queryset=CaseNeed.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["need"].queryset = CaseNeed.objects.filter(
            is_open=True, beneficiary__status=Beneficiary.APPROVED).select_related("beneficiary")
        if self.instance.pk and self.instance.beneficiary_id:
            self.fields["case_code"].initial = self.instance.beneficiary.case_no
        if self.case_required:
            self.fields["case_code"].required = True

    case_required = False

    def clean_case_code(self):
        code = (self.cleaned_data.get("case_code") or "").strip().upper()
        if not code:
            return None
        case = Beneficiary.objects.filter(case_no=code, status=Beneficiary.APPROVED).first()
        if case is None:
            raise forms.ValidationError(_("No approved case has this code."))
        return case

    def clean(self):
        data = super().clean()
        case, need = data.get("case_code"), data.get("need")
        if need and case and need.beneficiary_id != case.pk:
            self.add_error("need", _("This need belongs to another case."))
        self.instance.beneficiary = case or (need.beneficiary if need else None)
        return data


class DonationForm(CaseCodeForm):
    class Meta:
        model = Donation
        exclude = ("beneficiary",)


class SponsorshipForm(CaseCodeForm):
    case_required = True

    class Meta:
        model = Sponsorship
        exclude = ("beneficiary",)


@admin.register(Donor)
class DonorAdmin(admin.ModelAdmin):
    list_display = ("name", "donor_type", "phone", "email")
    list_filter = ("donor_type",)
    search_fields = ("name", "phone", "email")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "target", "start_date", "end_date", "fund", "project")
    search_fields = ("code", "name")


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    form = DonationForm
    list_display = ("receipt_no", "donor", "amount", "method", "purpose", "donation_date", "campaign", "case_code")
    list_filter = ("purpose", "method", "campaign")
    search_fields = ("receipt_no", "donor__name", "donor__phone", "beneficiary__case_no")
    autocomplete_fields = ("donor", "sponsorship", "campaign")

    @admin.display(description=_("case code"), ordering="beneficiary__case_no")
    def case_code(self, obj):
        return obj.beneficiary.case_no if obj.beneficiary_id else ""
    readonly_fields = ("receipt_no", "recorded_by")
    inlines = [AttachmentInline]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        stamp_attachments(request, formset)


@admin.register(Sponsorship)
class SponsorshipAdmin(admin.ModelAdmin):
    form = SponsorshipForm
    list_display = ("donor", "case_code", "monthly_amount", "start_date", "end_date", "status")
    list_filter = ("status",)
    search_fields = ("donor__name", "beneficiary__case_no")
    autocomplete_fields = ("donor",)

    @admin.display(description=_("case code"), ordering="beneficiary__case_no")
    def case_code(self, obj):
        return obj.beneficiary.case_no


@admin.register(Volunteer)
class VolunteerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "skills", "is_active")
    search_fields = ("name", "phone", "skills")


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("membership_no", "name", "phone", "paid_until_year", "status")
    search_fields = ("membership_no", "name", "national_id")
