"""Finance and accounting: chart of accounts, journal, payments, fixed assets.

Double entry: every journal entry balances (total debit = total credit). Each line can carry a
fund, a project and a department (cost centre), so reports can be cut by any of them.

Posted entries are never edited or deleted. A mistake is corrected by a reversing entry.
Manual journals and payments go through maker-checker approval. Entries made automatically
from other modules (donations, aid, payroll, purchases, stock) are posted at once: the source
document was already controlled in its own module.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BilingualName, Department, Fund, Project, next_number

CENT = Decimal("0.01")
ZERO = Decimal(0)


def money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


class FinanceError(Exception):
    pass


# ---------------------------------------------------------------- chart of accounts

class Account(BilingualName):
    ASSET, LIABILITY, NET_ASSETS, INCOME, EXPENSE = "asset", "liability", "net_assets", "income", "expense"
    KINDS = [(ASSET, _("Asset")), (LIABILITY, _("Liability")), (NET_ASSETS, _("Net assets / funds")),
             (INCOME, _("Income")), (EXPENSE, _("Expense"))]
    DEBIT_NATURE = (ASSET, EXPENSE)

    code = models.CharField(_("code"), max_length=20, unique=True)
    kind = models.CharField(_("type"), max_length=12, choices=KINDS)
    parent = models.ForeignKey("self", verbose_name=_("parent account"), null=True, blank=True,
                               related_name="children", on_delete=models.PROTECT)
    postable = models.BooleanField(_("entries allowed"), default=True,
                                   help_text=_("Untick for heading accounts that only group others."))
    contra = models.BooleanField(_("contra account"), default=False,
                                 help_text=_("e.g. accumulated depreciation: shown under assets with a credit balance."))
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("account")
        verbose_name_plural = _("chart of accounts")
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def debit_nature(self):
        return self.kind in self.DEBIT_NATURE

    def clean(self):
        if self.parent_id and self.parent.kind != self.kind:
            raise ValidationError({"parent": _("A sub-account must have the same type as its parent.")})
        if self.parent_id and self.parent.postable:
            raise ValidationError({"parent": _("The parent must be a heading account (entries not allowed).")})


class AccountMapping(models.Model):
    """Which account an automatic posting uses, e.g. 'income.zakat' → 4102 Zakat al-mal donations."""

    key = models.CharField(_("posting key"), max_length=60, unique=True)
    account = models.ForeignKey(Account, verbose_name=_("account"), on_delete=models.PROTECT,
                                limit_choices_to={"postable": True})
    description = models.CharField(_("used for"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("posting rule")
        verbose_name_plural = _("posting rules (automatic entries)")
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} → {self.account}"


def mapped(key, fallback=None):
    """The account for a posting key, trying 'a.b.c' then 'a.b' then fallback."""
    keys = [key]
    while "." in keys[-1]:
        keys.append(keys[-1].rsplit(".", 1)[0])
    if fallback:
        keys.append(fallback)
    found = {m.key: m.account for m in AccountMapping.objects.filter(key__in=keys).select_related("account")}
    for k in keys:
        if k in found:
            return found[k]
    raise FinanceError(_("No posting rule for '%(key)s'. Add it under Finance → Posting rules.") % {"key": key})


class FiscalYear(models.Model):
    year = models.PositiveSmallIntegerField(_("year"), unique=True)
    locked_through = models.DateField(_("books locked up to and including"), null=True, blank=True,
                                      help_text=_("Nothing can be posted on or before this date (month-end close)."))
    closed = models.BooleanField(_("year closed"), default=False)

    class Meta:
        verbose_name = _("financial year")
        verbose_name_plural = _("financial years")
        ordering = ["-year"]

    def __str__(self):
        return str(self.year)


def check_open(day):
    fy, _created = FiscalYear.objects.get_or_create(year=day.year)
    if fy.closed:
        raise FinanceError(_("The financial year %(y)s is closed.") % {"y": day.year})
    if fy.locked_through and day <= fy.locked_through:
        raise FinanceError(_("The books are locked up to %(d)s. Choose a later date or ask the finance manager.")
                           % {"d": fy.locked_through})


# ---------------------------------------------------------------- journal

class JournalEntry(models.Model):
    DRAFT, PENDING, POSTED, RETURNED, REJECTED = "draft", "pending", "posted", "returned", "rejected"
    STATUSES = [(DRAFT, _("Draft")), (PENDING, _("Awaiting approval")), (POSTED, _("Posted")),
                (RETURNED, _("Returned for changes")), (REJECTED, _("Rejected"))]
    SOURCES = [("manual", _("Manual journal")), ("opening", _("Opening balances")), ("donation", _("Donation")),
               ("aid", _("Aid to a case")), ("payroll", _("Payroll")), ("payment", _("Payment")),
               ("purchase", _("Purchasing")), ("stock", _("Stock")), ("depreciation", _("Depreciation")),
               ("reversal", _("Reversal"))]

    entry_no = models.CharField(_("entry no."), max_length=20, unique=True, editable=False)
    date = models.DateField(_("date"), default=timezone.localdate)
    description = models.CharField(_("description"), max_length=255)
    source = models.CharField(_("source"), max_length=15, choices=SOURCES, default="manual")
    # the document that produced an automatic entry, and which event (e.g. 'payroll.paid')
    source_type = models.ForeignKey(ContentType, null=True, blank=True, editable=False, on_delete=models.PROTECT)
    source_id = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    source_document = GenericForeignKey("source_type", "source_id")
    source_event = models.CharField(max_length=40, blank=True, editable=False)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=DRAFT, editable=False)
    reverses = models.OneToOneField("self", verbose_name=_("reverses entry"), null=True, blank=True, editable=False,
                                    related_name="reversed_by", on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("created by"), null=True, editable=False, related_name="+",
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("journal entry")
        verbose_name_plural = _("journal entries")
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["source_type", "source_id", "source_event"])]

    def __str__(self):
        return f"{self.entry_no} {self.description}"

    def save(self, *args, **kwargs):
        if self.pk and JournalEntry.objects.filter(pk=self.pk, status=self.POSTED).exists():
            raise FinanceError(_("A posted entry cannot be changed. Reverse it instead."))
        if not self.entry_no:
            self.entry_no = next_number("journal", self.date.year)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == self.POSTED:
            raise FinanceError(_("A posted entry cannot be deleted. Reverse it instead."))
        return super().delete(*args, **kwargs)

    def totals(self):
        t = self.lines.aggregate(d=Sum("debit"), c=Sum("credit"))
        return t["d"] or ZERO, t["c"] or ZERO

    def check_balanced(self):
        debit, credit = self.totals()
        if debit <= 0 or debit != credit:
            raise ValidationError(_("The entry does not balance: debit %(d)s, credit %(c)s.") % {"d": debit, "c": credit})

    def post(self):
        """Make the entry final. Only through approval (manual) or the posting service (automatic)."""
        check_open(self.date)
        self.check_balanced()
        JournalEntry.objects.filter(pk=self.pk).update(status=self.POSTED, posted_at=timezone.now())
        self.status = self.POSTED

    def _set(self, status):
        JournalEntry.objects.filter(pk=self.pk).update(status=status)
        self.status = status

    # maker-checker for manual journals, opening balances, depreciation and reversals
    approval_doc_type = "finance.journal"

    def approval_title(self):
        return f"{self.entry_no} — {self.description}"

    def approval_amount(self):
        return self.totals()[0]

    def on_approval_submitted(self, request):
        check_open(self.date)
        self.check_balanced()
        self._set(self.PENDING)

    def on_approval_approved(self, request):
        self.post()

    def on_approval_rejected(self, request):
        self._set(self.REJECTED)

    def on_approval_returned(self, request):
        self._set(self.RETURNED)

    def on_approval_cancelled(self, request):
        self._set(self.DRAFT)


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, related_name="lines", on_delete=models.CASCADE)
    account = models.ForeignKey(Account, verbose_name=_("account"), on_delete=models.PROTECT,
                                limit_choices_to={"postable": True, "is_active": True})
    debit = models.DecimalField(_("debit"), max_digits=14, decimal_places=2, default=0,
                                validators=[MinValueValidator(0)])
    credit = models.DecimalField(_("credit"), max_digits=14, decimal_places=2, default=0,
                                 validators=[MinValueValidator(0)])
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)
    project = models.ForeignKey(Project, verbose_name=_("project"), null=True, blank=True, on_delete=models.PROTECT)
    department = models.ForeignKey(Department, verbose_name=_("cost centre"), null=True, blank=True,
                                   on_delete=models.PROTECT)
    memo = models.CharField(_("memo"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("journal line")
        verbose_name_plural = _("journal lines")
        ordering = ["id"]

    def __str__(self):
        return f"{self.account.code} {self.debit or ''}/{self.credit or ''}"

    def clean(self):
        if (self.debit or 0) and (self.credit or 0):
            raise ValidationError(_("A line is either a debit or a credit, not both."))
        if not (self.debit or 0) and not (self.credit or 0):
            raise ValidationError(_("Enter a debit or a credit amount."))
        if self.account_id and not self.account.postable:
            raise ValidationError({"account": _("Choose an account that accepts entries, not a heading.")})

    def save(self, *args, **kwargs):
        if self.entry_id and JournalEntry.objects.filter(pk=self.entry_id, status=JournalEntry.POSTED).exists():
            raise FinanceError(_("A posted entry cannot be changed. Reverse it instead."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.entry.status == JournalEntry.POSTED:
            raise FinanceError(_("A posted entry cannot be changed. Reverse it instead."))
        return super().delete(*args, **kwargs)


class PostingIssue(models.Model):
    """An automatic entry that could not be made (missing posting rule, locked month...). Fix, then retry."""

    event = models.CharField(_("event"), max_length=40)
    source_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    source_id = models.PositiveBigIntegerField()
    source_document = GenericForeignKey("source_type", "source_id")
    message = models.TextField(_("problem"))
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)

    class Meta:
        verbose_name = _("posting problem")
        verbose_name_plural = _("posting problems")
        ordering = ["resolved_at", "-created_at"]

    def __str__(self):
        return f"{self.event}: {self.message[:60]}"


# ---------------------------------------------------------------- payments

class Payment(models.Model):
    """A payment voucher: supplier, staff advance, rent... Needs approval; posts Dr <what is paid> / Cr cash or bank."""

    METHODS = [("cash", _("Cash")), ("bank", _("Bank transfer")), ("check", _("Cheque"))]
    DRAFT, PENDING, APPROVED, PAID, RETURNED, REJECTED = "draft", "pending", "approved", "paid", "returned", "rejected"
    STATUSES = [(DRAFT, _("Draft")), (PENDING, _("Awaiting approval")), (APPROVED, _("Approved")), (PAID, _("Paid")),
                (RETURNED, _("Returned for changes")), (REJECTED, _("Rejected"))]

    payment_no = models.CharField(_("voucher no."), max_length=20, unique=True, editable=False)
    date = models.DateField(_("payment date"), default=timezone.localdate)
    payee = models.CharField(_("paid to"), max_length=160)
    amount = models.DecimalField(_("amount (EGP)"), max_digits=14, decimal_places=2, validators=[MinValueValidator(CENT)])
    method = models.CharField(_("method"), max_length=10, choices=METHODS, default="bank")
    reference = models.CharField(_("cheque / transfer reference"), max_length=60, blank=True)
    debit_account = models.ForeignKey(Account, verbose_name=_("charge to account"), on_delete=models.PROTECT,
                                      limit_choices_to={"postable": True, "is_active": True}, related_name="+")
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)
    project = models.ForeignKey(Project, verbose_name=_("project"), null=True, blank=True, on_delete=models.PROTECT)
    department = models.ForeignKey(Department, verbose_name=_("cost centre"), null=True, blank=True,
                                   on_delete=models.PROTECT)
    description = models.CharField(_("description"), max_length=255)
    # optional link to what is being paid (e.g. a supplier invoice); it is told when the payment is made
    for_type = models.ForeignKey(ContentType, null=True, blank=True, editable=False, on_delete=models.PROTECT)
    for_id = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    for_document = GenericForeignKey("for_type", "for_id")
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=DRAFT, editable=False)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("prepared by"), null=True, editable=False, related_name="+",
                                    on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("payment voucher")
        verbose_name_plural = _("payment vouchers")
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.payment_no} {self.payee}"

    def save(self, *args, **kwargs):
        if not self.payment_no:
            self.payment_no = next_number("payment", (self.date or timezone.localdate()).year)
        super().save(*args, **kwargs)

    def clean(self):
        doc = self.for_document
        if doc is not None and hasattr(doc, "amount_to_pay") and self.amount and self.amount > doc.amount_to_pay(exclude=self):
            raise ValidationError({"amount": _("More than what is still owed (%(a)s).") % {"a": doc.amount_to_pay(exclude=self)}})

    approval_doc_type = "finance.payment"

    def approval_title(self):
        return f"{self.payment_no} — {self.payee}"

    def approval_amount(self):
        return self.amount

    def approval_excluded_user_ids(self):
        return [self.prepared_by_id] if self.prepared_by_id else []

    def _set(self, status):
        Payment.objects.filter(pk=self.pk).update(status=status)
        self.status = status

    def on_approval_submitted(self, request):
        self.full_clean()
        self._set(self.PENDING)

    def on_approval_approved(self, request):
        self._set(self.APPROVED)

    def on_approval_rejected(self, request):
        self._set(self.REJECTED)

    def on_approval_returned(self, request):
        self._set(self.RETURNED)

    def mark_paid(self, day=None):
        """The money actually left: post the entry and tell the document that was paid."""
        from core.events import emit
        if self.status != self.APPROVED:
            raise FinanceError(_("Only an approved payment can be marked as paid."))
        if day:
            Payment.objects.filter(pk=self.pk).update(date=day)
            self.date = day
        self._set(self.PAID)
        emit("payment.paid", self)
        doc = self.for_document
        if doc is not None and hasattr(doc, "on_paid"):
            doc.on_paid(self)


# ---------------------------------------------------------------- fixed assets

class AssetCategory(BilingualName):
    code = models.CharField(_("code"), max_length=20, unique=True)
    asset_account = models.ForeignKey(Account, verbose_name=_("asset account"), related_name="+",
                                      on_delete=models.PROTECT, limit_choices_to={"kind": Account.ASSET})
    accumulated_account = models.ForeignKey(Account, verbose_name=_("accumulated depreciation account"),
                                            related_name="+", on_delete=models.PROTECT,
                                            limit_choices_to={"kind": Account.ASSET})
    expense_account = models.ForeignKey(Account, verbose_name=_("depreciation expense account"), related_name="+",
                                        on_delete=models.PROTECT, limit_choices_to={"kind": Account.EXPENSE})
    life_months = models.PositiveSmallIntegerField(_("default useful life (months)"))

    class Meta:
        verbose_name = _("asset category")
        verbose_name_plural = _("asset categories")
        ordering = ["code"]


class FixedAsset(models.Model):
    """Register entry. Buying the asset is booked by the supplier invoice or a journal; this record drives depreciation."""

    asset_no = models.CharField(_("asset no."), max_length=20, unique=True, editable=False)
    name = models.CharField(_("description"), max_length=160)
    category = models.ForeignKey(AssetCategory, verbose_name=_("category"), on_delete=models.PROTECT)
    serial = models.CharField(_("serial / plate no."), max_length=60, blank=True)
    acquired_on = models.DateField(_("in use from"))
    cost = models.DecimalField(_("cost (EGP)"), max_digits=14, decimal_places=2, validators=[MinValueValidator(CENT)])
    salvage_value = models.DecimalField(_("value at end of life"), max_digits=14, decimal_places=2, default=0)
    life_months = models.PositiveSmallIntegerField(_("useful life (months)"), null=True, blank=True,
                                                   help_text=_("Empty = the category's default."))
    department = models.ForeignKey(Department, verbose_name=_("cost centre"), null=True, blank=True,
                                   on_delete=models.PROTECT)
    project = models.ForeignKey(Project, verbose_name=_("project"), null=True, blank=True, on_delete=models.PROTECT)
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)
    location = models.CharField(_("location"), max_length=120, blank=True)
    custodian = models.ForeignKey("hr.Employee", verbose_name=_("custodian"), null=True, blank=True,
                                  on_delete=models.SET_NULL)
    disposed_on = models.DateField(_("disposed on"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("fixed asset")
        verbose_name_plural = _("fixed assets")
        ordering = ["asset_no"]

    def __str__(self):
        return f"{self.asset_no} {self.name}"

    def save(self, *args, **kwargs):
        if not self.asset_no:
            self.asset_no = next_number("asset", self.acquired_on.year)
        super().save(*args, **kwargs)

    def clean(self):
        if self.cost is not None and self.salvage_value is not None and self.salvage_value >= self.cost:
            raise ValidationError({"salvage_value": _("Must be lower than the cost.")})

    @property
    def life(self):
        return self.life_months or self.category.life_months

    def depreciated_until(self, day):
        return self.depreciation_lines.filter(run__entry__status=JournalEntry.POSTED,
                                              run__end__lte=day).aggregate(s=Sum("amount"))["s"] or ZERO

    def book_value(self, day=None):
        return self.cost - self.depreciated_until(day or timezone.localdate())


class DepreciationRun(models.Model):
    """Monthly straight-line depreciation for all assets in use. Creates a journal that needs approval."""

    year = models.PositiveSmallIntegerField(_("year"))
    month = models.PositiveSmallIntegerField(_("month"))
    end = models.DateField(editable=False)
    entry = models.OneToOneField(JournalEntry, null=True, blank=True, editable=False, on_delete=models.PROTECT)
    total = models.DecimalField(_("total"), max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = _("depreciation run")
        verbose_name_plural = _("depreciation runs")
        unique_together = [("year", "month")]
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.month:02d}/{self.year}"

    @property
    def status(self):
        return self.entry.get_status_display() if self.entry_id else _("Not calculated")


class DepreciationLine(models.Model):
    run = models.ForeignKey(DepreciationRun, related_name="lines", on_delete=models.CASCADE)
    asset = models.ForeignKey(FixedAsset, related_name="depreciation_lines", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
