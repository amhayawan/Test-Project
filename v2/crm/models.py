from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from core.models import Fund, Project, next_number

ZAKAT_PURPOSES = ("zakat", "zakat_fitr")


class Donor(models.Model):
    INDIVIDUAL, COMPANY = "individual", "company"
    TYPES = [(INDIVIDUAL, _("Individual")), (COMPANY, _("Company / organisation"))]

    name = models.CharField(_("name"), max_length=160)
    donor_type = models.CharField(_("type"), max_length=20, choices=TYPES, default=INDIVIDUAL)
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    email = models.EmailField(_("email"), blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("donor")
        verbose_name_plural = _("donors")
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_donated(self):
        return self.donations.aggregate(t=Sum("amount"))["t"] or Decimal(0)


class Campaign(models.Model):
    code = models.CharField(_("code"), max_length=20, unique=True)
    name = models.CharField(_("name"), max_length=160)
    target = models.DecimalField(_("target (EGP)"), max_digits=14, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"), null=True, blank=True)
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)
    project = models.ForeignKey(Project, verbose_name=_("project"), null=True, blank=True, on_delete=models.PROTECT)
    description = models.TextField(_("description"), blank=True)

    class Meta:
        verbose_name = _("campaign")
        verbose_name_plural = _("campaigns")
        ordering = ["-start_date"]

    def __str__(self):
        return self.name

    @property
    def raised(self):
        return self.donations.aggregate(t=Sum("amount"))["t"] or Decimal(0)


class Donation(models.Model):
    METHODS = [("cash", _("Cash")), ("bank", _("Bank transfer")), ("instapay", _("InstaPay")),
               ("wallet", _("Mobile wallet")), ("check", _("Cheque")), ("in_kind", _("In kind"))]
    PURPOSES = [("general", _("General donation")), ("zakat", _("Zakat al-mal")), ("zakat_fitr", _("Zakat al-fitr")),
                ("sadaqa", _("Sadaqa")), ("orphans", _("Orphan sponsorship")), ("medical", _("Medical")),
                ("education", _("Education")), ("food", _("Food / Ramadan boxes")), ("udhiya", _("Udhiya"))]

    receipt_no = models.CharField(_("receipt no."), max_length=20, unique=True, editable=False)
    donor = models.ForeignKey(Donor, verbose_name=_("donor"), related_name="donations", on_delete=models.PROTECT)
    amount = models.DecimalField(_("amount (EGP)"), max_digits=14, decimal_places=2)
    method = models.CharField(_("payment method"), max_length=20, choices=METHODS, default="cash")
    purpose = models.CharField(_("purpose"), max_length=20, choices=PURPOSES, default="general")
    donation_date = models.DateField(_("date"), default=date.today)
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)
    campaign = models.ForeignKey(Campaign, verbose_name=_("campaign"), null=True, blank=True,
                                 related_name="donations", on_delete=models.PROTECT)
    # Earmarking (optional)
    beneficiary = models.ForeignKey("cases.Beneficiary", verbose_name=_("earmarked for case"), null=True,
                                    blank=True, related_name="earmarked_donations", on_delete=models.PROTECT)
    need = models.ForeignKey("cases.CaseNeed", verbose_name=_("earmarked for need"), null=True, blank=True,
                             related_name="donations", on_delete=models.PROTECT)
    sponsorship = models.ForeignKey("Sponsorship", verbose_name=_("sponsorship payment"), null=True, blank=True,
                                    related_name="payments", on_delete=models.PROTECT)
    notes = models.TextField(_("notes"), blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, editable=False, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("donation")
        verbose_name_plural = _("donations")
        ordering = ["-donation_date", "-id"]

    def __str__(self):
        return self.receipt_no or "—"

    def clean(self):
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = _("The amount must be greater than zero.")
        spons = self.sponsorship
        if spons:
            if self.donor_id and spons.donor_id != self.donor_id:
                errors["sponsorship"] = _("This sponsorship belongs to another donor.")
            self.beneficiary = self.beneficiary or spons.beneficiary
            if self.beneficiary_id != spons.beneficiary_id:
                errors["sponsorship"] = _("The sponsorship is not for the selected case.")
            if not self.need_id and spons.need_id:
                self.need = spons.need
        if self.need_id:
            self.beneficiary = self.beneficiary or self.need.beneficiary
            if self.beneficiary_id != self.need.beneficiary_id:
                errors["need"] = _("The need does not belong to the selected case.")
        if self.beneficiary_id:
            case = self.beneficiary
            changed_case = not self.pk or Donation.objects.filter(pk=self.pk).exclude(beneficiary=case).exists()
            if case.status != case.APPROVED and changed_case:
                errors["beneficiary"] = _("Donations can only be earmarked for approved cases.")
            elif self.purpose in ZAKAT_PURPOSES and case.zakat_eligible != "yes":
                errors["purpose"] = _("This case is not eligible for zakat according to the social research.")
        if self.fund_id and self.purpose in ZAKAT_PURPOSES and self.fund.kind != Fund.ZAKAT:
            errors["fund"] = _("Zakat must go to a zakat fund.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if isinstance(self.donation_date, str):
            self.donation_date = date.fromisoformat(self.donation_date)
        if not self.receipt_no:
            self.receipt_no = next_number("receipt", (self.donation_date or date.today()).year)
        super().save(*args, **kwargs)


class Sponsorship(models.Model):
    ACTIVE, PAUSED, ENDED = "active", "paused", "ended"
    STATUSES = [(ACTIVE, _("Active")), (PAUSED, _("Paused")), (ENDED, _("Ended"))]

    donor = models.ForeignKey(Donor, verbose_name=_("sponsor"), related_name="sponsorships", on_delete=models.PROTECT)
    beneficiary = models.ForeignKey("cases.Beneficiary", verbose_name=_("case"), related_name="sponsorships",
                                    on_delete=models.PROTECT)
    need = models.ForeignKey("cases.CaseNeed", verbose_name=_("need"), null=True, blank=True,
                             on_delete=models.PROTECT)
    monthly_amount = models.DecimalField(_("monthly amount (EGP)"), max_digits=12, decimal_places=2)
    start_date = models.DateField(_("start date"), default=date.today)
    end_date = models.DateField(_("end date"), null=True, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=ACTIVE)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("sponsorship")
        verbose_name_plural = _("sponsorships")
        ordering = ["-id"]

    def __str__(self):
        return f"{self.donor} ← {self.beneficiary.case_no}"

    def clean(self):
        errors = {}
        if self.beneficiary_id and self.beneficiary.status != self.beneficiary.APPROVED and not self.pk:
            errors["beneficiary"] = _("Sponsorships can only be created for approved cases.")
        if self.need_id and self.beneficiary_id and self.need.beneficiary_id != self.beneficiary_id:
            errors["need"] = _("The need does not belong to the selected case.")
        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors["end_date"] = _("The end date is before the start date.")
        if errors:
            raise ValidationError(errors)

    @property
    def paid_total(self):
        return self.payments.aggregate(t=Sum("amount"))["t"] or Decimal(0)

    def months_due(self, today=None):
        today = today or date.today()
        end = min(today, self.end_date) if self.end_date else today
        if end < self.start_date:
            return 0
        return (end.year - self.start_date.year) * 12 + end.month - self.start_date.month + 1

    @property
    def arrears(self):
        return max(self.monthly_amount * self.months_due() - self.paid_total, Decimal(0))

    @property
    def paid_this_month(self):
        today = date.today()
        return self.payments.filter(donation_date__year=today.year, donation_date__month=today.month).exists()


class Volunteer(models.Model):
    name = models.CharField(_("name"), max_length=160)
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    email = models.EmailField(_("email"), blank=True)
    skills = models.CharField(_("skills"), max_length=255, blank=True)
    availability = models.CharField(_("availability"), max_length=120, blank=True)
    join_date = models.DateField(_("join date"), null=True, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("volunteer")
        verbose_name_plural = _("volunteers")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Member(models.Model):
    """General-assembly member (annual dues)."""

    STATUSES = [("active", _("Active")), ("inactive", _("Inactive")), ("honorary", _("Honorary"))]

    membership_no = models.CharField(_("membership no."), max_length=20, unique=True)
    name = models.CharField(_("name"), max_length=160)
    national_id = models.CharField(_("national ID"), max_length=14, unique=True, null=True, blank=True)
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    join_date = models.DateField(_("join date"), null=True, blank=True)
    paid_until_year = models.PositiveSmallIntegerField(_("dues paid until"), null=True, blank=True)
    status = models.CharField(_("membership type"), max_length=10, choices=STATUSES, default="active")
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("general-assembly member")
        verbose_name_plural = _("general-assembly members")
        ordering = ["membership_no"]

    def __str__(self):
        return f"{self.membership_no} {self.name}"
