from django.contrib import admin

from core.admin import AttachmentInline, stamp_attachments

from .models import Campaign, Donation, Donor, Member, Sponsorship, Volunteer


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
    list_display = ("receipt_no", "donor", "amount", "method", "purpose", "donation_date", "campaign", "beneficiary")
    list_filter = ("purpose", "method", "campaign")
    search_fields = ("receipt_no", "donor__name", "donor__phone")
    autocomplete_fields = ("donor", "beneficiary", "need", "sponsorship", "campaign")
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
    list_display = ("donor", "beneficiary", "monthly_amount", "start_date", "end_date", "status")
    list_filter = ("status",)
    search_fields = ("donor__name", "beneficiary__name", "beneficiary__case_no")
    autocomplete_fields = ("donor", "beneficiary", "need")


@admin.register(Volunteer)
class VolunteerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "skills", "is_active")
    search_fields = ("name", "phone", "skills")


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("membership_no", "name", "phone", "paid_until_year", "status")
    search_fields = ("membership_no", "name", "national_id")
