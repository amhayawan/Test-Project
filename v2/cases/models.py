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
    MARITAL = [("widow", _("Widow")), ("divorced", _("Divorced")), ("married_m", _("Married (man)")),
               ("married_f", _("Married (woman)")), ("single", _("Single"))]
    BATHROOM = [("private", _("Private")), ("shared", _("Shared"))]
    FLOORS = [("tiles", _("Tiles")), ("ceramic", _("Ceramic")), ("other", _("Other"))]
    MATERIALS = [("rural", _("Rural (mud)")), ("brick", _("Brick")), ("plastered", _("Plastered"))]
    LIVESTOCK_OWNER = [("own", _("The family")), ("others", _("Others"))]
    ASSESSMENTS = [("urgent", _("Poor and in urgent need of assistance")), ("medium", _("Medium condition")),
                   ("not_needed", _("Not in need (standard of living is high)"))]

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
    # ---- standard field research form (page 1)
    form_no = models.CharField(_("research form no."), max_length=30, blank=True)
    marital_status = models.CharField(_("marital status of the head"), max_length=12, choices=MARITAL, blank=True)
    has_engaged_daughter = models.CharField(_("is there an engaged daughter?"), max_length=3, choices=YES_NO, blank=True)
    engaged_daughter_name = models.CharField(_("daughter's name"), max_length=160, blank=True)
    wedding_date = models.DateField(_("wedding date"), null=True, blank=True)
    marriage_needs_provided = models.TextField(_("marriage needs already provided (what, and from whom)"), blank=True)
    marriage_needs_remaining = models.TextField(_("marriage needs remaining"), blank=True)
    income_salaries = models.DecimalField(_("family work salaries (total)"), max_digits=10, decimal_places=2, default=0)
    income_takaful = models.DecimalField(_("social solidarity pension (Takaful and Karama)"), max_digits=10,
                                         decimal_places=2, default=0)
    income_insurance = models.DecimalField(_("social insurance pension"), max_digits=10, decimal_places=2, default=0)
    income_charities = models.DecimalField(_("Sharia association / charities"), max_digits=10, decimal_places=2, default=0)
    income_benefactors = models.DecimalField(_("benefactors (relatives / neighbours)"), max_digits=10, decimal_places=2,
                                             default=0)
    benefactors_who = models.CharField(_("which benefactors"), max_length=120, blank=True)
    exp_food_daily = models.DecimalField(_("daily food cost"), max_digits=10, decimal_places=2, default=0)
    exp_rent = models.DecimalField(_("rent"), max_digits=10, decimal_places=2, default=0)
    exp_transport = models.DecimalField(_("transport"), max_digits=10, decimal_places=2, default=0)
    exp_education = models.DecimalField(_("school fees and private lessons"), max_digits=10, decimal_places=2, default=0)
    exp_installments = models.DecimalField(_("instalments, if any"), max_digits=10, decimal_places=2, default=0)
    exp_electricity = models.DecimalField(_("electricity bill"), max_digits=10, decimal_places=2, default=0)
    exp_water = models.DecimalField(_("water bill"), max_digits=10, decimal_places=2, default=0)
    exp_phone = models.DecimalField(_("telephone bill"), max_digits=10, decimal_places=2, default=0)
    exp_gas = models.DecimalField(_("gas bill"), max_digits=10, decimal_places=2, default=0)
    # ---- page 2: housing
    rooms = models.PositiveSmallIntegerField(_("number of rooms"), null=True, blank=True)
    house_area = models.CharField(_("house area"), max_length=40, blank=True)
    bathroom = models.CharField(_("bathroom"), max_length=10, choices=BATHROOM, blank=True)
    floor_type = models.CharField(_("floor"), max_length=10, choices=FLOORS, blank=True)
    building_material = models.CharField(_("walls and roof"), max_length=10, choices=MATERIALS, blank=True)
    water_connection = models.CharField(_("water connection"), max_length=3, choices=YES_NO, blank=True)
    water_distance = models.CharField(_("if not, distance to nearest water point"), max_length=80, blank=True)
    needs_roof = models.CharField(_("needs a roof?"), max_length=3, choices=YES_NO, blank=True)
    roof_room_area = models.CharField(_("if so, room area"), max_length=40, blank=True)
    other_appliances = models.CharField(_("other electrical appliances"), max_length=255, blank=True)
    ration_card_members = models.PositiveSmallIntegerField(_("members on the ration card"), null=True, blank=True)
    no_ration_card_reason = models.CharField(_("reason if there is no ration card"), max_length=160, blank=True)
    livestock = models.CharField(_("does the family keep livestock?"), max_length=3, choices=YES_NO, blank=True)
    livestock_count = models.PositiveSmallIntegerField(_("number of animals"), null=True, blank=True)
    livestock_owner = models.CharField(_("animals belong to"), max_length=10, choices=LIVESTOCK_OWNER, blank=True)
    extra_burdens = models.TextField(_("additional burdens"), blank=True)
    smoker = models.CharField(_("is anyone a smoker?"), max_length=3, choices=YES_NO, blank=True)
    need_medical = models.BooleanField(_("medical"), default=False)
    need_marriage = models.BooleanField(_("marriage"), default=False)
    need_project = models.BooleanField(_("small project"), default=False)
    need_appliances = models.BooleanField(_("home appliances"), default=False)
    need_monthly = models.BooleanField(_("monthly assistance"), default=False)
    need_other = models.CharField(_("other needs"), max_length=160, blank=True)
    assessment = models.CharField(_("researcher's assessment"), max_length=10, choices=ASSESSMENTS, blank=True)
    research_findings = models.TextField(_("researcher's opinion and description of the family's need"), blank=True)
    recommendation = models.TextField(_("recommendation"), blank=True)
    referred_at = models.DateTimeField(_("referred to the Projects Department"), null=True, blank=True, editable=False)
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
            ("view_case_summary", _("Can see approved cases by code only (no personal details)")),
        ]

    def __str__(self):
        return f"{self.case_no} {self.name}"

    def save(self, *args, **kwargs):
        if not self.case_no:
            self.case_no = next_number("case", timezone.localdate().year)
        if self.total_income:               # the research form's income table is the source of truth
            self.monthly_income = self.total_income
        created = self.pk is None
        super().save(*args, **kwargs)
        if created:
            HouseholdItem.create_checklist(self)

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
        if not self.assessment:
            missing.append(_("researcher's assessment"))
        return missing

    INCOME_FIELDS = ("income_salaries", "income_takaful", "income_insurance", "income_charities", "income_benefactors")
    EXPENSE_FIELDS = ("exp_rent", "exp_transport", "exp_education", "exp_installments", "exp_electricity",
                      "exp_water", "exp_phone", "exp_gas")

    @property
    def total_income(self):
        return sum((getattr(self, f) or 0 for f in self.INCOME_FIELDS), Decimal(0))

    @property
    def total_expenses(self):
        """Monthly: daily food × 30 plus the monthly items."""
        return (self.exp_food_daily or 0) * 30 + sum((getattr(self, f) or 0 for f in self.EXPENSE_FIELDS), Decimal(0))

    @property
    def monthly_gap(self):
        return self.total_expenses - self.total_income

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
        # Accepted by the Research Department Manager: referred to the Projects Department for assistance.
        Beneficiary.objects.filter(pk=self.pk).update(status=self.APPROVED, referred_at=timezone.now())

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
    JOB_STABILITY = [("stable", _("Stable")), ("irregular", _("Irregular"))]

    beneficiary = models.ForeignKey(Beneficiary, related_name="family", on_delete=models.CASCADE)
    name = models.CharField(_("name"), max_length=160)
    relation = models.CharField(_("relation"), max_length=20, choices=RELATIONS)
    national_id = models.CharField(_("national ID"), max_length=14, blank=True, validators=[national_id_validator])
    birth_year = models.PositiveSmallIntegerField(_("birth year"), null=True, blank=True)
    gender = models.CharField(_("gender"), max_length=1, choices=[("m", _("Male")), ("f", _("Female"))], blank=True)
    age = models.PositiveSmallIntegerField(_("age"), null=True, blank=True)
    education = models.CharField(_("education"), max_length=80, blank=True)
    education_work = models.CharField(_("work"), max_length=160, blank=True)
    monthly_income = models.DecimalField(_("average income"), max_digits=12, decimal_places=2, null=True, blank=True)
    job_stability = models.CharField(_("work stability"), max_length=12, choices=JOB_STABILITY, blank=True)
    not_working_reason = models.CharField(_("reason for not working"), max_length=120, blank=True)
    able_to_work = models.CharField(_("able to work (researcher's view)"), max_length=3, choices=YES_NO, blank=True)
    health = models.CharField(_("health"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("family member")
        verbose_name_plural = _("family members")
        ordering = ["id"]

    def __str__(self):
        return self.name


class MedicalCondition(models.Model):
    """'Illnesses in the family' table of the research form."""

    beneficiary = models.ForeignKey(Beneficiary, related_name="medical", on_delete=models.CASCADE)
    patient = models.CharField(_("patient's name"), max_length=160)
    illness = models.CharField(_("illness"), max_length=160)
    treatment_cost = models.DecimalField(_("treatment cost (monthly)"), max_digits=10, decimal_places=2, default=0)
    state_coverage = models.CharField(_("covered by the state"), max_length=120, blank=True)

    class Meta:
        verbose_name = _("illness in the family")
        verbose_name_plural = _("illnesses in the family")
        ordering = ["id"]

    def __str__(self):
        return f"{self.patient}: {self.illness}"


class HouseholdItem(models.Model):
    """Appliances and furniture checklist of the research form (rows are created with each case)."""

    APPLIANCE, FURNITURE = "appliance", "furniture"
    ITEMS = [
        ("cooker", APPLIANCE, _("Cooker / gas stove")), ("washer", APPLIANCE, _("Washing machine")),
        ("fridge", APPLIANCE, _("Refrigerator")), ("tv", APPLIANCE, _("Television")), ("fan", APPLIANCE, _("Fan")),
        ("phone", APPLIANCE, _("Telephone")), ("heater", APPLIANCE, _("Water heater")),
        ("cylinder", APPLIANCE, _("Gas cylinder")), ("computer", APPLIANCE, _("Computer")),
        ("bed", FURNITURE, _("Bed")), ("mattress", FURNITURE, _("Mattress")), ("blanket", FURNITURE, _("Blanket")),
        ("sofa", FURNITURE, _("Traditional sofa (kanaba)")), ("chairs", FURNITURE, _("Chairs")),
        ("wardrobe", FURNITURE, _("Wardrobe")), ("salon", FURNITURE, _("Salon (sitting set)")),
        ("carpet", FURNITURE, _("Carpet")), ("mat", FURNITURE, _("Floor mat")),
    ]
    CONDITIONS = [("good", _("Good")), ("medium", _("Medium")), ("poor", _("Poor"))]

    beneficiary = models.ForeignKey(Beneficiary, related_name="household", on_delete=models.CASCADE)
    item = models.CharField(_("item"), max_length=12, choices=[(c, l) for c, _k, l in ITEMS])
    kind = models.CharField(max_length=10, editable=False)
    present = models.CharField(_("available"), max_length=3, choices=YES_NO, blank=True)
    count = models.PositiveSmallIntegerField(_("number"), null=True, blank=True)
    condition = models.CharField(_("condition"), max_length=6, choices=CONDITIONS, blank=True)

    class Meta:
        verbose_name = _("household item")
        verbose_name_plural = _("appliances and furniture")
        ordering = ["id"]
        unique_together = [("beneficiary", "item")]

    def __str__(self):
        return self.get_item_display()

    @classmethod
    def create_checklist(cls, case):
        cls.objects.bulk_create([cls(beneficiary=case, item=code, kind=kind) for code, kind, _label in cls.ITEMS],
                                ignore_conflicts=True)


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

    FUNDING_LABELS = {"closed": _("Closed"), "funded": _("Fully collected"), "partial": _("Partly collected"),
                      "open": _("Not collected yet")}

    @property
    def funding_label(self):
        """What researchers may know: collected or not, never donors or amounts."""
        return self.FUNDING_LABELS[self.funding_state]

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
    PAID_BY = [("cash", _("Cash")), ("bank", _("Bank transfer")), ("stock", _("Goods from the store"))]
    TYPES = [("cash", _("Cash")), ("food", _("Food")), ("medical", _("Medical")), ("education", _("Education")),
             ("clothes", _("Clothes")), ("housing", _("Housing / repairs")), ("other", _("Other"))]

    aid_no = models.CharField(_("aid no."), max_length=20, unique=True, editable=False)
    beneficiary = models.ForeignKey(Beneficiary, verbose_name=_("case"), related_name="aids", on_delete=models.PROTECT)
    need = models.ForeignKey(CaseNeed, verbose_name=_("need"), null=True, blank=True, on_delete=models.PROTECT)
    aid_type = models.CharField(_("type"), max_length=20, choices=TYPES, default="cash")
    value = models.DecimalField(_("value (EGP)"), max_digits=12, decimal_places=2)
    fund = models.ForeignKey(Fund, verbose_name=_("paid from fund"), null=True, blank=True, on_delete=models.PROTECT)
    project = models.ForeignKey("core.Project", verbose_name=_("project"), null=True, blank=True,
                                on_delete=models.PROTECT, related_name="aids")
    paid_by = models.CharField(_("given as"), max_length=10, choices=PAID_BY, default="cash",
                               help_text=_("Goods from the store are issued by the storekeeper against this aid."))
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

    def mark_delivered(self, day, **extra):
        """Record delivery; finance books the expense (cash/bank now, goods via the stock issue)."""
        from core.events import emit
        self.status, self.delivered_on = self.DELIVERED, day
        self.save(update_fields=["status", "delivered_on"])
        emit("aid.delivered", self, **extra)

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
