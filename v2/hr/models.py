"""Human resources: structure, employees, contracts, documents, assignments, pay and payroll.

Salaries are sensitive: every money field here is only shown to users with "hr.view_salary".
Payroll rates (income tax brackets, social insurance) are configuration, never code: the
association's payroll specialist enters them per year, and payroll refuses to run without them.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BilingualName, Department, Project, next_number

CENT = Decimal("0.01")
national_id_validator = RegexValidator(r"^\d{14}$", _("The national ID must be exactly 14 digits."))


def money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def month_bounds(year, month):
    start = date(year, month, 1)
    end = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))
    return start, end


def overlaps(start, end, period_start, period_end):
    return start <= period_end and (end is None or end >= period_start)


# ---------------------------------------------------------------- structure

class Grade(BilingualName):
    code = models.CharField(_("code"), max_length=20, unique=True)
    level = models.PositiveSmallIntegerField(_("level"), default=1)
    min_salary = models.DecimalField(_("minimum basic salary"), max_digits=12, decimal_places=2, null=True, blank=True)
    max_salary = models.DecimalField(_("maximum basic salary"), max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = _("grade")
        verbose_name_plural = _("grades")
        ordering = ["level", "code"]


class Position(BilingualName):
    """A post in the organisation chart, with its job description."""

    code = models.CharField(_("code"), max_length=20, unique=True)
    department = models.ForeignKey(Department, verbose_name=_("department"), on_delete=models.PROTECT,
                                   related_name="positions")
    grade = models.ForeignKey(Grade, verbose_name=_("grade"), null=True, blank=True, on_delete=models.PROTECT)
    reports_to = models.ForeignKey("self", verbose_name=_("reports to"), null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="direct_reports")
    headcount = models.PositiveSmallIntegerField(_("approved headcount"), default=1)
    purpose = models.TextField(_("job purpose"), blank=True)
    responsibilities = models.TextField(_("responsibilities"), blank=True)
    qualifications = models.TextField(_("qualifications and experience"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("position / job description")
        verbose_name_plural = _("positions / job descriptions")
        ordering = ["department__code", "code"]

    @property
    def filled(self):
        return self.employees.filter(status__in=(Employee.ACTIVE, Employee.ON_LEAVE)).count()


# ---------------------------------------------------------------- employees

class EmployeeQuerySet(models.QuerySet):
    def current(self):
        return self.filter(status__in=(Employee.ACTIVE, Employee.ON_LEAVE))


class Employee(models.Model):
    ACTIVE, ON_LEAVE, TERMINATED = "active", "on_leave", "terminated"
    STATUSES = [(ACTIVE, _("Active")), (ON_LEAVE, _("On long leave")), (TERMINATED, _("Left"))]
    GENDERS = [("m", _("Male")), ("f", _("Female"))]
    MARITAL = [("single", _("Single")), ("married", _("Married")), ("divorced", _("Divorced")),
               ("widowed", _("Widowed"))]

    employee_no = models.CharField(_("employee no."), max_length=20, unique=True, editable=False)
    name_ar = models.CharField(_("name (Arabic)"), max_length=160)
    name_en = models.CharField(_("name (English)"), max_length=160, blank=True)
    national_id = models.CharField(_("national ID"), max_length=14, unique=True, validators=[national_id_validator])
    birth_date = models.DateField(_("birth date"), null=True, blank=True)
    gender = models.CharField(_("gender"), max_length=1, choices=GENDERS, blank=True)
    marital_status = models.CharField(_("marital status"), max_length=10, choices=MARITAL, blank=True)
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    email = models.EmailField(_("email"), blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    emergency_contact = models.CharField(_("emergency contact (name and phone)"), max_length=200, blank=True)
    qualification = models.CharField(_("highest qualification"), max_length=160, blank=True)
    military_status = models.CharField(_("military service status"), max_length=60, blank=True)
    social_insurance_no = models.CharField(_("social insurance no."), max_length=30, blank=True)
    # organisation
    department = models.ForeignKey(Department, verbose_name=_("home department"), on_delete=models.PROTECT,
                                   related_name="employees")
    position = models.ForeignKey(Position, verbose_name=_("position"), null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="employees")
    grade = models.ForeignKey(Grade, verbose_name=_("grade"), null=True, blank=True, on_delete=models.PROTECT)
    manager = models.ForeignKey("self", verbose_name=_("line manager"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="team")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name=_("system login"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="employee")
    hire_date = models.DateField(_("hire date"))
    end_date = models.DateField(_("end of service"), null=True, blank=True)
    end_reason = models.CharField(_("reason for leaving"), max_length=200, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=ACTIVE)
    # payment (sensitive)
    bank_name = models.CharField(_("bank"), max_length=80, blank=True)
    bank_account = models.CharField(_("bank account / IBAN"), max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = EmployeeQuerySet.as_manager()

    class Meta:
        verbose_name = _("employee")
        verbose_name_plural = _("employees")
        ordering = ["employee_no"]
        permissions = [
            ("view_salary", _("Can see salaries, pay items and payslips")),
            ("run_payroll", _("Can prepare payroll runs")),
        ]

    def __str__(self):
        return f"{self.employee_no} {self.name}"

    @property
    def name(self):
        from django.utils.translation import get_language
        return self.name_en if (get_language() or "ar").startswith("en") and self.name_en else self.name_ar

    def save(self, *args, **kwargs):
        if not self.employee_no:
            self.employee_no = next_number("employee", (self.hire_date or timezone.localdate()).year)
        super().save(*args, **kwargs)

    def clean(self):
        if self.end_date and self.hire_date and self.end_date < self.hire_date:
            raise ValidationError({"end_date": _("The end of service is before the hire date.")})
        if self.status == self.TERMINATED and not self.end_date:
            raise ValidationError({"end_date": _("Enter the end-of-service date for someone who has left.")})
        if self.manager_id and self.manager_id == self.pk:
            raise ValidationError({"manager": _("An employee cannot manage themselves.")})

    def contract_on(self, day):
        return self.contracts.filter(start_date__lte=day).filter(Q(end_date__isnull=True) | Q(end_date__gte=day)) \
            .exclude(status=Contract.CANCELLED).order_by("-start_date").first()


class Contract(models.Model):
    TYPES = [("permanent", _("Open-ended")), ("fixed", _("Fixed term")), ("part_time", _("Part time")),
             ("consultant", _("Consultant")), ("trainee", _("Trainee"))]
    ACTIVE, CANCELLED = "active", "cancelled"
    STATUSES = [(ACTIVE, _("Active")), (CANCELLED, _("Cancelled"))]

    contract_no = models.CharField(_("contract no."), max_length=20, unique=True, editable=False)
    employee = models.ForeignKey(Employee, verbose_name=_("employee"), related_name="contracts",
                                 on_delete=models.PROTECT)
    contract_type = models.CharField(_("type"), max_length=12, choices=TYPES, default="fixed")
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"), null=True, blank=True)
    probation_end = models.DateField(_("end of probation"), null=True, blank=True)
    basic_salary = models.DecimalField(_("basic monthly salary (EGP)"), max_digits=12, decimal_places=2)
    weekly_hours = models.PositiveSmallIntegerField(_("weekly hours"), default=40)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=ACTIVE)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("contract")
        verbose_name_plural = _("contracts")
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.contract_no} {self.employee.name}"

    def save(self, *args, **kwargs):
        if not self.contract_no:
            self.contract_no = next_number("contract", self.start_date.year)
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors["end_date"] = _("The end date is before the start date.")
        if self.contract_type == "fixed" and not self.end_date:
            errors["end_date"] = _("A fixed-term contract needs an end date.")
        if self.basic_salary is not None and self.basic_salary <= 0:
            errors["basic_salary"] = _("The salary must be greater than zero.")
        grade = getattr(self.employee, "grade", None) if self.employee_id else None
        if grade and self.basic_salary and (
                (grade.min_salary and self.basic_salary < grade.min_salary)
                or (grade.max_salary and self.basic_salary > grade.max_salary)):
            errors["basic_salary"] = _("The salary is outside the range of the employee's grade.")
        if self.employee_id and self.start_date and self.status == self.ACTIVE:
            others = self.employee.contracts.exclude(pk=self.pk).exclude(status=self.CANCELLED)
            for c in others:
                if overlaps(c.start_date, c.end_date, self.start_date, self.end_date or date.max):
                    errors["start_date"] = _("This contract overlaps another active contract (%(no)s).") % {
                        "no": c.contract_no}
                    break
        if errors:
            raise ValidationError(errors)

    @property
    def days_to_end(self):
        return (self.end_date - timezone.localdate()).days if self.end_date else None


class Assignment(models.Model):
    """Share of an employee's time (and cost) charged to a department and optionally a project."""

    employee = models.ForeignKey(Employee, verbose_name=_("employee"), related_name="assignments",
                                 on_delete=models.CASCADE)
    department = models.ForeignKey(Department, verbose_name=_("department"), on_delete=models.PROTECT)
    project = models.ForeignKey(Project, verbose_name=_("project"), null=True, blank=True, on_delete=models.PROTECT)
    percent = models.DecimalField(_("share of time (%)"), max_digits=5, decimal_places=2,
                                  validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal(100))])
    start_date = models.DateField(_("from"))
    end_date = models.DateField(_("to"), null=True, blank=True)

    class Meta:
        verbose_name = _("assignment")
        verbose_name_plural = _("assignments")
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee.name} → {self.project or self.department} {self.percent}%"

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": _("The end date is before the start date.")})
        if self.project_id and self.department_id and self.project.department_id != self.department_id:
            raise ValidationError({"project": _("The project belongs to another department.")})
        if self.employee_id and self.start_date and self.percent:
            overlapping = [a for a in self.employee.assignments.exclude(pk=self.pk)
                           if overlaps(a.start_date, a.end_date, self.start_date, self.end_date or date.max)]
            if sum((a.percent for a in overlapping), Decimal(0)) + self.percent > 100:
                raise ValidationError({"percent": _("Assignments for the same dates would exceed 100%.")})


# ---------------------------------------------------------------- pay structure

class PayComponent(BilingualName):
    EARNING, DEDUCTION = "earning", "deduction"
    KINDS = [(EARNING, _("Earning / allowance")), (DEDUCTION, _("Deduction"))]

    code = models.CharField(_("code"), max_length=20, unique=True)
    kind = models.CharField(_("type"), max_length=10, choices=KINDS)
    taxable = models.BooleanField(_("subject to income tax"), default=True)
    insurable = models.BooleanField(_("counts for social insurance"), default=False)

    class Meta:
        verbose_name = _("pay component")
        verbose_name_plural = _("pay components")
        ordering = ["kind", "code"]


class EmployeePayItem(models.Model):
    """A recurring allowance or deduction for one employee: fixed amount or % of basic salary."""

    employee = models.ForeignKey(Employee, verbose_name=_("employee"), related_name="pay_items",
                                 on_delete=models.CASCADE)
    component = models.ForeignKey(PayComponent, verbose_name=_("component"), on_delete=models.PROTECT)
    amount = models.DecimalField(_("fixed amount (EGP)"), max_digits=12, decimal_places=2, null=True, blank=True)
    percent_of_basic = models.DecimalField(_("or % of basic"), max_digits=5, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(_("from"))
    end_date = models.DateField(_("to"), null=True, blank=True)

    class Meta:
        verbose_name = _("employee pay item")
        verbose_name_plural = _("employee pay items")

    def __str__(self):
        return f"{self.employee.name}: {self.component}"

    def clean(self):
        if (self.amount is None) == (self.percent_of_basic is None):
            raise ValidationError(_("Enter either a fixed amount or a percentage of basic, not both."))

    def value_for(self, basic):
        return money(self.amount if self.amount is not None else basic * self.percent_of_basic / 100)


class Incentive(models.Model):
    """One-off bonus, incentive, overtime or penalty. Must be approved before it reaches payroll."""

    TYPES = [("incentive", _("Incentive")), ("bonus", _("Bonus")), ("overtime", _("Overtime")),
             ("penalty", _("Penalty deduction"))]
    DRAFT, PENDING, APPROVED, REJECTED, RETURNED = "draft", "pending", "approved", "rejected", "returned"
    STATUSES = [(DRAFT, _("Draft")), (PENDING, _("Awaiting approval")), (APPROVED, _("Approved")),
                (REJECTED, _("Rejected")), (RETURNED, _("Returned for changes"))]

    employee = models.ForeignKey(Employee, verbose_name=_("employee"), related_name="incentives",
                                 on_delete=models.PROTECT)
    kind = models.CharField(_("type"), max_length=10, choices=TYPES)
    amount = models.DecimalField(_("amount (EGP)"), max_digits=12, decimal_places=2)
    pay_year = models.PositiveSmallIntegerField(_("pay year"))
    pay_month = models.PositiveSmallIntegerField(_("pay month"), validators=[MinValueValidator(1), MaxValueValidator(12)])
    reason = models.CharField(_("reason"), max_length=255)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=DRAFT, editable=False)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("requested by"), null=True, editable=False, related_name="+",
                                     on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("incentive / bonus / penalty")
        verbose_name_plural = _("incentives / bonuses / penalties")
        ordering = ["-pay_year", "-pay_month"]

    def __str__(self):
        return f"{self.employee.name} {self.get_kind_display()} {self.pay_month}/{self.pay_year}"

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": _("The amount must be greater than zero.")})

    approval_doc_type = "hr.incentive"

    def approval_title(self):
        return f"{self.employee.name} — {self.get_kind_display()} {self.pay_month}/{self.pay_year}"

    def approval_amount(self):
        return self.amount

    def _set(self, status):
        Incentive.objects.filter(pk=self.pk).update(status=status)
        self.status = status

    def on_approval_submitted(self, request):
        if PayrollRun.objects.filter(year=self.pay_year, month=self.pay_month,
                                     status__in=(PayrollRun.APPROVED, PayrollRun.PAID)).exists():
            raise ValidationError(_("Payroll for that month is already approved. Choose a later month."))
        self._set(self.PENDING)

    def on_approval_approved(self, request):
        self._set(self.APPROVED)

    def on_approval_rejected(self, request):
        self._set(self.REJECTED)

    def on_approval_returned(self, request):
        self._set(self.RETURNED)


# ---------------------------------------------------------------- statutory rules (configured, not coded)

class InsuranceRule(models.Model):
    """Social insurance rates and wage limits for one year. Enter the official values each year."""

    year = models.PositiveSmallIntegerField(_("year"), unique=True)
    employee_rate = models.DecimalField(_("employee share (%)"), max_digits=5, decimal_places=2)
    employer_rate = models.DecimalField(_("employer share (%)"), max_digits=5, decimal_places=2)
    min_insurable = models.DecimalField(_("minimum insurable wage (monthly)"), max_digits=12, decimal_places=2)
    max_insurable = models.DecimalField(_("maximum insurable wage (monthly)"), max_digits=12, decimal_places=2)
    source = models.CharField(_("source / decree reference"), max_length=255)
    verified_by = models.CharField(_("verified by (payroll specialist)"), max_length=120)

    class Meta:
        verbose_name = _("social insurance rule")
        verbose_name_plural = _("social insurance rules")
        ordering = ["-year"]

    def __str__(self):
        return str(self.year)


class TaxBracket(models.Model):
    """Annual salary income-tax brackets for one year. Enter the official values each year."""

    year = models.PositiveSmallIntegerField(_("year"))
    lower = models.DecimalField(_("annual income from"), max_digits=14, decimal_places=2)
    upper = models.DecimalField(_("annual income to (empty = no limit)"), max_digits=14, decimal_places=2,
                                null=True, blank=True)
    rate = models.DecimalField(_("rate (%)"), max_digits=5, decimal_places=2)
    annual_exemption = models.DecimalField(_("personal annual exemption (enter on the first bracket)"),
                                           max_digits=12, decimal_places=2, default=0)
    source = models.CharField(_("source / law reference"), max_length=255)

    class Meta:
        verbose_name = _("income tax bracket")
        verbose_name_plural = _("income tax brackets")
        ordering = ["year", "lower"]

    def __str__(self):
        return f"{self.year}: {self.lower}–{self.upper or '∞'} @ {self.rate}%"


def annual_tax(year, annual_taxable):
    brackets = list(TaxBracket.objects.filter(year=year).order_by("lower"))
    if not brackets:
        return None
    income = max(annual_taxable - max(b.annual_exemption for b in brackets), Decimal(0))
    tax = Decimal(0)
    for b in brackets:
        if income <= b.lower:
            break
        top = income if b.upper is None else min(income, b.upper)
        tax += (top - b.lower) * b.rate / 100
    return money(tax)


# ---------------------------------------------------------------- payroll

class PayrollRun(models.Model):
    DRAFT, PENDING, APPROVED, RETURNED, REJECTED, PAID = "draft", "pending", "approved", "returned", "rejected", "paid"
    STATUSES = [(DRAFT, _("Draft")), (PENDING, _("Awaiting approval")), (APPROVED, _("Approved")),
                (RETURNED, _("Returned for changes")), (REJECTED, _("Rejected")), (PAID, _("Paid"))]

    year = models.PositiveSmallIntegerField(_("year"))
    month = models.PositiveSmallIntegerField(_("month"), validators=[MinValueValidator(1), MaxValueValidator(12)])
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=DRAFT, editable=False)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("prepared by"), null=True, editable=False, related_name="+",
                                    on_delete=models.SET_NULL)
    calculated_at = models.DateTimeField(null=True, editable=False)
    total_gross = models.DecimalField(_("total gross"), max_digits=14, decimal_places=2, default=0, editable=False)
    total_net = models.DecimalField(_("total net"), max_digits=14, decimal_places=2, default=0, editable=False)
    total_cost = models.DecimalField(_("total cost to the association"), max_digits=14, decimal_places=2,
                                     default=0, editable=False)

    class Meta:
        verbose_name = _("payroll run")
        verbose_name_plural = _("payroll runs")
        unique_together = [("year", "month")]
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.month:02d}/{self.year}"

    @property
    def locked(self):
        return self.status in (self.PENDING, self.APPROVED, self.PAID)

    approval_doc_type = "hr.payroll"

    def approval_excluded_user_ids(self):
        return [self.prepared_by_id] if self.prepared_by_id else []

    def approval_title(self):
        return f"{_('Payroll')} {self}"

    def approval_amount(self):
        return self.total_net

    def _set(self, status):
        PayrollRun.objects.filter(pk=self.pk).update(status=status)
        self.status = status

    def on_approval_submitted(self, request):
        if not self.payslips.exists():
            raise ValidationError(_("Calculate the payroll before sending it for approval."))
        self._set(self.PENDING)

    def on_approval_approved(self, request):
        from core.events import emit
        self._set(self.APPROVED)
        emit("payroll.approved", self)

    def on_approval_rejected(self, request):
        self._set(self.REJECTED)

    def on_approval_returned(self, request):
        self._set(self.RETURNED)

    def mark_paid(self, day):
        from core.events import emit
        self._set(self.PAID)
        emit("payroll.paid", self, day=day)


class Payslip(models.Model):
    run = models.ForeignKey(PayrollRun, related_name="payslips", on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, related_name="payslips", on_delete=models.PROTECT)
    days_paid = models.PositiveSmallIntegerField(default=0)
    basic = models.DecimalField(max_digits=12, decimal_places=2)
    lines = models.JSONField(default=list)            # [{"code","name","kind","amount"}]
    gross = models.DecimalField(max_digits=12, decimal_places=2)
    insurable_wage = models.DecimalField(max_digits=12, decimal_places=2)
    insurance_employee = models.DecimalField(max_digits=12, decimal_places=2)
    insurance_employer = models.DecimalField(max_digits=12, decimal_places=2)
    income_tax = models.DecimalField(max_digits=12, decimal_places=2)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2)
    net = models.DecimalField(max_digits=12, decimal_places=2)
    employer_cost = models.DecimalField(max_digits=12, decimal_places=2)
    allocation = models.JSONField(default=list)       # [{"department","project","percent","amount"}]
    bank_name = models.CharField(max_length=80, blank=True)
    bank_account = models.CharField(max_length=40, blank=True)

    class Meta:
        verbose_name = _("payslip")
        verbose_name_plural = _("payslips")
        unique_together = [("run", "employee")]
        ordering = ["employee__employee_no"]

    def __str__(self):
        return f"{self.run} {self.employee.name}"


class Appraisal(models.Model):
    RATINGS = [(5, _("Outstanding")), (4, _("Exceeds expectations")), (3, _("Meets expectations")),
               (2, _("Needs improvement")), (1, _("Unsatisfactory"))]
    STATUSES = [("draft", _("Draft")), ("discussed", _("Discussed with employee")), ("final", _("Final"))]

    employee = models.ForeignKey(Employee, verbose_name=_("employee"), related_name="appraisals",
                                 on_delete=models.PROTECT)
    period_start = models.DateField(_("period from"))
    period_end = models.DateField(_("period to"))
    reviewer = models.ForeignKey(Employee, verbose_name=_("reviewer"), related_name="+", on_delete=models.PROTECT)
    objectives = models.TextField(_("objectives and results"), blank=True)
    strengths = models.TextField(_("strengths"), blank=True)
    development = models.TextField(_("areas to develop"), blank=True)
    rating = models.PositiveSmallIntegerField(_("overall rating"), choices=RATINGS, null=True, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default="draft")

    class Meta:
        verbose_name = _("performance appraisal")
        verbose_name_plural = _("performance appraisals")
        ordering = ["-period_end"]

    def __str__(self):
        return f"{self.employee.name} {self.period_end:%Y}"

    def clean(self):
        if self.reviewer_id and self.reviewer_id == self.employee_id:
            raise ValidationError({"reviewer": _("Employees cannot appraise themselves.")})


# ---------------------------------------------------------------- leave (rules are configuration, verified by a specialist)

class LeaveType(BilingualName):
    """A kind of leave, permission or mission, with its rules.

    Day counts are NOT shipped. HR enters them from the labour law / internal policy, and a
    second person holding "verify HR rules" (the labour-law / payroll specialist) signs them off.
    Any later change removes the sign-off, and unverified types cannot be requested.
    """

    DAYS, HOURS = "days", "hours"
    UNITS = [(DAYS, _("Days")), (HOURS, _("Hours"))]
    ABSENCE, DUTY = "absence", "duty"
    NATURES = [(ABSENCE, _("Absence (leave or permission)")), (DUTY, _("On duty outside the office (mission)"))]
    ANY, FEMALE, MALE = "", "f", "m"
    GENDERS = [(ANY, _("Everyone")), (FEMALE, _("Women only")), (MALE, _("Men only"))]

    code = models.CharField(_("code"), max_length=20, unique=True)
    unit = models.CharField(_("counted in"), max_length=5, choices=UNITS, default=DAYS)
    nature = models.CharField(_("nature"), max_length=8, choices=NATURES, default=ABSENCE)
    calendar_days = models.BooleanField(_("count calendar days (include weekends and holidays)"), default=False)
    paid_percent = models.DecimalField(_("paid by the association (%)"), max_digits=5, decimal_places=2, default=100,
                                       validators=[MinValueValidator(0), MaxValueValidator(100)],
                                       help_text=_("100 = fully paid; 0 = unpaid (deducted in payroll)."))
    deduct_from = models.ForeignKey("self", verbose_name=_("taken from the balance of"), null=True, blank=True,
                                    on_delete=models.PROTECT, help_text=_("e.g. casual leave is taken from annual leave."))
    max_per_request = models.DecimalField(_("maximum per request"), max_digits=6, decimal_places=2, null=True, blank=True)
    max_per_month = models.DecimalField(_("maximum per month"), max_digits=6, decimal_places=2, null=True, blank=True)
    max_per_year = models.DecimalField(_("maximum per year"), max_digits=6, decimal_places=2, null=True, blank=True)
    max_times_in_service = models.PositiveSmallIntegerField(_("maximum times during service"), null=True, blank=True)
    min_service_months = models.PositiveSmallIntegerField(_("minimum service before use (months)"), default=0)
    gender = models.CharField(_("for"), max_length=1, choices=GENDERS, blank=True, default=ANY)
    needs_document = models.BooleanField(_("supporting document required"), default=False,
                                         help_text=_("e.g. a medical certificate for sick leave."))
    source = models.CharField(_("source (law article or internal policy)"), max_length=255, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("last changed by"), null=True, editable=False, related_name="+",
                                   on_delete=models.SET_NULL)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("verified by"), null=True, blank=True,
                                    editable=False, related_name="+", on_delete=models.SET_NULL)
    verified_at = models.DateTimeField(_("verified at"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("leave type")
        verbose_name_plural = _("leave types and rules")
        ordering = ["code"]
        permissions = [("verify_hr_rules", _("Can verify leave rules (labour-law specialist)"))]

    @property
    def is_verified(self):
        return bool(self.verified_by_id and self.verified_at)

    def balance_type(self):
        return self.deduct_from or self

    def clean(self):
        if self.unit == self.HOURS and self.paid_percent is not None and self.paid_percent < 100:
            raise ValidationError({"paid_percent": _("Hourly permissions must be paid; record unpaid time as a day leave.")})
        if self.deduct_from_id and self.deduct_from_id == self.pk:
            raise ValidationError({"deduct_from": _("A leave type cannot take from its own balance.")})
        if self.deduct_from_id and self.deduct_from.unit != self.unit:
            raise ValidationError({"deduct_from": _("Both leave types must be counted in the same unit.")})


class LeaveEntitlement(models.Model):
    """Yearly balance for a leave type, by length of service and/or age. The highest matching line applies."""

    leave_type = models.ForeignKey(LeaveType, related_name="entitlements", on_delete=models.CASCADE)
    min_service_months = models.PositiveSmallIntegerField(_("from service (months)"), default=0)
    min_age = models.PositiveSmallIntegerField(_("and age at least (years)"), null=True, blank=True)
    days_per_year = models.DecimalField(_("balance per year"), max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _("yearly balance rule")
        verbose_name_plural = _("yearly balance rules")
        ordering = ["min_service_months"]

    def __str__(self):
        return f"{self.leave_type}: {self.days_per_year}"


class PublicHoliday(models.Model):
    """Official holidays (not counted inside leave). Islamic holidays move every year: enter them yearly."""

    date = models.DateField(_("date"), unique=True)
    name_ar = models.CharField(_("name (Arabic)"), max_length=120)
    name_en = models.CharField(_("name (English)"), max_length=120, blank=True)

    class Meta:
        verbose_name = _("official holiday")
        verbose_name_plural = _("official holidays")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} {self.name_ar}"


class LeaveAdjustment(models.Model):
    """Opening balance, carried-over days or a correction, entered by HR with a reason."""

    employee = models.ForeignKey(Employee, verbose_name=_("employee"), related_name="leave_adjustments",
                                 on_delete=models.PROTECT)
    leave_type = models.ForeignKey(LeaveType, verbose_name=_("leave type"), on_delete=models.PROTECT)
    year = models.PositiveSmallIntegerField(_("year"))
    days = models.DecimalField(_("days (+ add / - remove)"), max_digits=6, decimal_places=2)
    reason = models.CharField(_("reason"), max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("created by"), null=True, editable=False, related_name="+",
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("leave balance adjustment")
        verbose_name_plural = _("leave balance adjustments")
        ordering = ["-year", "-created_at"]

    def __str__(self):
        return f"{self.employee} {self.leave_type} {self.year}: {self.days:+}"


class LeaveRequestQuerySet(models.QuerySet):
    def counting(self):
        """Requests that use up balance or block the dates: waiting or approved."""
        return self.filter(status__in=(LeaveRequest.PENDING, LeaveRequest.APPROVED))


class LeaveRequest(models.Model):
    DRAFT, PENDING, APPROVED, REJECTED, RETURNED, CANCELLED = (
        "draft", "pending", "approved", "rejected", "returned", "cancelled")
    STATUSES = [(DRAFT, _("Draft")), (PENDING, _("Awaiting approval")), (APPROVED, _("Approved")),
                (REJECTED, _("Rejected")), (RETURNED, _("Returned for changes")), (CANCELLED, _("Cancelled"))]

    employee = models.ForeignKey(Employee, verbose_name=_("employee"), related_name="leave_requests",
                                 on_delete=models.PROTECT)
    leave_type = models.ForeignKey(LeaveType, verbose_name=_("leave type"), on_delete=models.PROTECT)
    start_date = models.DateField(_("from"))
    end_date = models.DateField(_("to"))
    hours = models.DecimalField(_("hours (permissions only)"), max_digits=4, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(_("days / hours counted"), max_digits=6, decimal_places=2, default=0, editable=False)
    reason = models.CharField(_("reason / notes"), max_length=255, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=DRAFT, editable=False)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("requested by"), null=True, editable=False, related_name="+",
                                     on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LeaveRequestQuerySet.as_manager()

    class Meta:
        verbose_name = _("leave request")
        verbose_name_plural = _("leave requests")
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee.name} — {self.leave_type} {self.start_date}"

    def clean(self):
        from . import leave
        leave.validate(self)

    def save(self, *args, **kwargs):
        from . import leave
        if self.leave_type_id and self.start_date and self.end_date:
            self.amount = leave.count(self)
        super().save(*args, **kwargs)

    approval_doc_type = "hr.leave"

    def approval_title(self):
        return (f"{self.employee.name} — {self.leave_type} {self.start_date:%Y-%m-%d} → {self.end_date:%Y-%m-%d} "
                f"({self.amount.normalize():f})")

    def approval_amount(self):
        return None

    def approval_excluded_user_ids(self):
        return [self.employee.user_id] if self.employee.user_id else []

    def approval_step_user_ids(self, step):
        """The 'line manager' step goes to this employee's own manager (HR manager if there is none)."""
        if step.role.name != "line_manager":
            return None
        mgr = self.employee.manager
        if mgr and mgr.user_id and mgr.user.is_active and mgr.user_id != self.employee.user_id:
            return [mgr.user_id]
        from django.contrib.auth import get_user_model
        return list(get_user_model().objects.filter(is_active=True, groups__name="hr_manager")
                    .exclude(pk=self.employee.user_id or 0).values_list("pk", flat=True))

    def _set(self, status):
        LeaveRequest.objects.filter(pk=self.pk).update(status=status)
        self.status = status

    def on_approval_submitted(self, request):
        from . import leave
        leave.validate(self, submitting=True)
        self._set(self.PENDING)

    def on_approval_approved(self, request):
        self._set(self.APPROVED)

    def on_approval_rejected(self, request):
        self._set(self.REJECTED)

    def on_approval_returned(self, request):
        self._set(self.RETURNED)

    def on_approval_cancelled(self, request):
        self._set(self.CANCELLED)
