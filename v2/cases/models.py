from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Department, Fund, Project, next_number

national_id_validator = RegexValidator(r"^\d{14}$", _("The national ID must be exactly 14 digits."))
YES_NO = [("yes", _("Yes")), ("no", _("No"))]


class BeneficiaryQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Researchers see only cases assigned to them; others need the 'view all cases' permission."""
        if user.has_perm("cases.view_all_cases"):
            return self
        if user.has_perm("cases.view_beneficiary"):
            return self.filter(researcher=user)
        return self.none()


class Beneficiary(models.Model):
    UNDER_STUDY, RECOMMENDED, APPROVED, REJECTED, SUSPENDED = (
        "under_study", "recommended", "approved", "rejected", "suspended")
    STATUSES = [(UNDER_STUDY, _("Under study")), (RECOMMENDED, _("Awaiting approval")), (APPROVED, _("Approved")),
                (REJECTED, _("Rejected")), (SUSPENDED, _("Suspended"))]
    CATEGORIES = [("poor_family", _("Family in need")), ("orphan", _("Orphan")), ("widow", _("Widow / divorcee")),
                  ("elderly", _("Elderly")), ("disabled", _("Person with disability")), ("sick", _("Patient")),
                  ("student", _("Student"))]
    HOUSING_TYPES = [("owned", _("Owned")), ("rent_old", _("Old rent")), ("rent_new", _("New rent")),
                     ("relatives", _("With relatives")), ("free", _("Free / shelter"))]
    HOUSING_CONDITIONS = [("good", _("Good")), ("fair", _("Fair")), ("poor", _("Poor")), ("unsafe", _("Unsafe"))]

    case_no = models.CharField(_("case no."), max_length=20, unique=True, editable=False)
    name = models.CharField(_("name"), max_length=160)
    national_id = models.CharField(_("national ID"), max_length=14, unique=True, null=True, blank=True,
                                   validators=[national_id_validator])
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    area = models.CharField(_("area"), max_length=80, blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    category = models.CharField(_("category"), max_length=20, choices=CATEGORIES, default="poor_family")
    family_size = models.PositiveSmallIntegerField(_("family size"), default=1)
    monthly_income = models.DecimalField(_("monthly income (EGP)"), max_digits=12, decimal_places=2, default=0)
    status = models.CharField(_("status"), max_length=20, choices=STATUSES, default=UNDER_STUDY, editable=False)
    department = models.ForeignKey(Department, verbose_name=_("department"), null=True, blank=True,
                                   on_delete=models.PROTECT)
    project = models.ForeignKey(Project, verbose_name=_("project"), null=True, blank=True, on_delete=models.PROTECT)
    notes = models.TextField(_("intake notes"), blank=True)
    # social research
    researcher = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("researcher"), null=True, blank=True,
                                   related_name="assigned_cases", on_delete=models.PROTECT)
    visit_date = models.DateField(_("field visit date"), null=True, blank=True)
    zakat_eligible = models.CharField(_("eligible for zakat"), max_length=3, choices=YES_NO, blank=True)
    housing_type = models.CharField(_("housing type"), max_length=20, choices=HOUSING_TYPES, blank=True)
    housing_condition = models.CharField(_("housing condition"), max_length=20, choices=HOUSING_CONDITIONS, blank=True)
    health_summary = models.TextField(_("family health"), blank=True)
    debts = models.DecimalField(_("debts (EGP)"), max_digits=12, decimal_places=2, null=True, blank=True)
    research_findings = models.TextField(_("research findings"), blank=True)
    recommendation = models.TextField(_("recommendation"), blank=True)
    next_review_date = models.DateField(_("next re-assessment"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, editable=False, related_name="+",
                                   on_delete=models.SET_NULL)

    objects = BeneficiaryQuerySet.as_manager()

    class Meta:
        verbose_name = _("case / beneficiary")
        verbose_name_plural = _("cases / beneficiaries")
        ordering = ["-created_at"]
        permissions = [
            ("view_all_cases", _("Can see all cases (not only assigned ones)")),
            ("assign_case", _("Can assign cases to researchers")),
            ("recommend_case", _("Can submit a case for approval")),
            ("approve_case", _("Can approve, reject or return cases")),
            ("view_case_funding", _("Can see donors and amounts linked to cases")),
        ]

    def __str__(self):
        return f"{self.case_no} {self.name}"

    def save(self, *args, **kwargs):
        if not self.case_no:
            self.case_no = next_number("case", timezone.localdate().year)
        super().save(*args, **kwargs)

    # ---- research
    @property
    def research_missing(self):
        missing = []
        if not self.visit_date:
            missing.append(_("field visit date"))
        if not self.research_findings.strip():
            missing.append(_("research findings"))
        if not self.recommendation.strip():
            missing.append(_("recommendation"))
        if not self.zakat_eligible:
            missing.append(_("zakat eligibility"))
        return missing

    def can_edit_research(self, user):
        if user.has_perm("cases.approve_case"):
            return self.status in (self.UNDER_STUDY, self.APPROVED, self.SUSPENDED)
        return self.status == self.UNDER_STUDY and self.researcher_id == user.pk

    # ---- maker-checker (approvals engine)
    approval_doc_type = "cases.case"

    def approval_title(self):
        return f"{self.case_no} — {self.name}"

    def approval_amount(self):
        return None

    def on_approval_submitted(self, request):
        if self.research_missing:
            raise ValidationError(_("Complete the research first: %(m)s") % {"m": ", ".join(map(str, self.research_missing))})
        Beneficiary.objects.filter(pk=self.pk).update(status=self.RECOMMENDED)
        self.status = self.RECOMMENDED

    def on_approval_approved(self, request):
        Beneficiary.objects.filter(pk=self.pk).update(status=self.APPROVED)

    def on_approval_rejected(self, request):
        Beneficiary.objects.filter(pk=self.pk).update(status=self.REJECTED)

    def on_approval_returned(self, request):
        Beneficiary.objects.filter(pk=self.pk).update(status=self.UNDER_STUDY)

    # ---- money
    @property
    def total_aid(self):
        return self.aids.filter(status__in=(Aid.APPROVED, Aid.DELIVERED)).aggregate(t=Sum("value"))["t"] or Decimal(0)


class FamilyMember(models.Model):
    RELATIONS = [("head", _("Head of family")), ("wife", _("Wife")), ("husband", _("Husband")), ("son", _("Son")),
                 ("daughter", _("Daughter")), ("father", _("Father")), ("mother", _("Mother")), ("other", _("Other"))]

    beneficiary = models.ForeignKey(Beneficiary, related_name="family", on_delete=models.CASCADE)
    name = models.CharField(_("name"), max_length=160)
    relation = models.CharField(_("relation"), max_length=20, choices=RELATIONS)
    national_id = models.CharField(_("national ID"), max_length=14, blank=True, validators=[national_id_validator])
    birth_year = models.PositiveSmallIntegerField(_("birth year"), null=True, blank=True)
    gender = models.CharField(_("gender"), max_length=1, choices=[("m", _("Male")), ("f", _("Female"))], blank=True)
    education_work = models.CharField(_("education / work"), max_length=160, blank=True)
    health = models.CharField(_("health"), max_length=200, blank=True)
    monthly_income = models.DecimalField(_("monthly income"), max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = _("family member")
        verbose_name_plural = _("family members")
        ordering = ["id"]

    def __str__(self):
        return self.name


class CaseNeed(models.Model):
    TYPES = [("monthly", _("Monthly support")), ("food", _("Food")), ("medical", _("Medical / surgery")),
             ("education", _("Education")), ("housing", _("Housing / repairs")), ("debt", _("Debt repayment")),
             ("marriage", _("Marriage preparation")), ("project", _("Small business")), ("other", _("Other"))]
    PRIORITIES = [("urgent", _("Urgent")), ("high", _("High")), ("normal", _("Normal"))]
    FREQUENCIES = [("once", _("One-off")), ("monthly", _("Monthly"))]

    beneficiary = models.ForeignKey(Beneficiary, related_name="needs", on_delete=models.PROTECT)
    need_type = models.CharField(_("type"), max_length=20, choices=TYPES)
    description = models.CharField(_("description"), max_length=255)
    amount_needed = models.DecimalField(_("amount needed (EGP)"), max_digits=12, decimal_places=2)
    frequency = models.CharField(_("frequency"), max_length=10, choices=FREQUENCIES, default="once")
    priority = models.CharField(_("priority"), max_length=10, choices=PRIORITIES, default="normal")
    is_open = models.BooleanField(_("open"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("need")
        verbose_name_plural = _("needs")
        ordering = ["id"]

    def __str__(self):
        return f"{self.beneficiary.name} — {self.description}"

    @property
    def funded(self):
        """Money earmarked to this need; monthly needs count the current month only."""
        qs = self.donations.all()
        if self.frequency == "monthly":
            today = date.today()
            qs = qs.filter(donation_date__year=today.year, donation_date__month=today.month)
        return qs.aggregate(t=Sum("amount"))["t"] or Decimal(0)

    @property
    def funding_state(self):
        if not self.is_open:
            return "closed"
        funded = self.funded
        if funded >= self.amount_needed:
            return "funded"
        return "partial" if funded > 0 else "open"


class Aid(models.Model):
    """Aid given to a case. Goes through maker-checker approval before it can be delivered."""

    DRAFT, PENDING, APPROVED, REJECTED, RETURNED, DELIVERED = (
        "draft", "pending", "approved", "rejected", "returned", "delivered")
    STATUSES = [(DRAFT, _("Draft")), (PENDING, _("Awaiting approval")), (APPROVED, _("Approved")),
                (REJECTED, _("Rejected")), (RETURNED, _("Returned for changes")), (DELIVERED, _("Delivered"))]
    TYPES = [("cash", _("Cash")), ("food", _("Food")), ("medical", _("Medical")), ("education", _("Education")),
             ("clothes", _("Clothes")), ("housing", _("Housing / repairs")), ("other", _("Other"))]

    aid_no = models.CharField(_("aid no."), max_length=20, unique=True, editable=False)
    beneficiary = models.ForeignKey(Beneficiary, verbose_name=_("case"), related_name="aids", on_delete=models.PROTECT)
    need = models.ForeignKey(CaseNeed, verbose_name=_("need"), null=True, blank=True, on_delete=models.PROTECT)
    aid_type = models.CharField(_("type"), max_length=20, choices=TYPES, default="cash")
    value = models.DecimalField(_("value (EGP)"), max_digits=12, decimal_places=2)
    fund = models.ForeignKey(Fund, verbose_name=_("paid from fund"), null=True, blank=True, on_delete=models.PROTECT)
    description = models.CharField(_("description"), max_length=255, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=DRAFT, editable=False)
    delivered_on = models.DateField(_("delivered on"), null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, editable=False, related_name="+",
                                     on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("aid")
        verbose_name_plural = _("aid")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.aid_no} {self.beneficiary.name}"

    def clean(self):
        errors = {}
        if self.value is not None and self.value <= 0:
            errors["value"] = _("The value must be greater than zero.")
        if self.beneficiary_id and self.beneficiary.status != Beneficiary.APPROVED:
            errors["beneficiary"] = _("Aid can only be given to approved cases.")
        if self.need_id and self.need.beneficiary_id != self.beneficiary_id:
            errors["need"] = _("The need does not belong to this case.")
        if self.fund_id and self.fund.kind == Fund.ZAKAT and self.beneficiary_id \
                and self.beneficiary.zakat_eligible != "yes":
            errors["fund"] = _("This case is not eligible for zakat.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.aid_no:
            self.aid_no = next_number("aid", timezone.localdate().year)
        super().save(*args, **kwargs)

    approval_doc_type = "cases.aid"

    def approval_title(self):
        return f"{self.aid_no} — {self.beneficiary.name} — {self.get_aid_type_display()}"

    def approval_amount(self):
        return self.value

    def _set(self, status):
        Aid.objects.filter(pk=self.pk).update(status=status)
        self.status = status

    def on_approval_submitted(self, request):
        self._set(self.PENDING)

    def on_approval_approved(self, request):
        self._set(self.APPROVED)

    def on_approval_rejected(self, request):
        self._set(self.REJECTED)

    def on_approval_returned(self, request):
        self._set(self.RETURNED)
