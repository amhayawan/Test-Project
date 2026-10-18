"""Project management around core.Project: profile, approved budget, milestones and tasks.

Money is never booked here. Actual spend, funding raised and staff cost are read from the posted
finance journal (lines tagged with the project); aid and beneficiaries from case management.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from core.models import Fund, Project

ZERO = Decimal(0)


class ProjectProfile(models.Model):
    DRAFT, PENDING, APPROVED, RETURNED, REJECTED = "draft", "pending", "approved", "returned", "rejected"
    STATUSES = [(DRAFT, _("Draft")), (PENDING, _("Awaiting approval")), (APPROVED, _("Approved")),
                (RETURNED, _("Returned for changes")), (REJECTED, _("Rejected"))]

    project = models.OneToOneField(Project, verbose_name=_("project"), related_name="profile",
                                   on_delete=models.CASCADE)
    objectives = models.TextField(_("objectives"), blank=True)
    target_beneficiaries = models.PositiveIntegerField(_("target number of beneficiaries"), default=0)
    location = models.CharField(_("location"), max_length=160, blank=True)
    grant_reference = models.CharField(_("donor / grant reference"), max_length=160, blank=True)
    budget_status = models.CharField(_("budget status"), max_length=10, choices=STATUSES, default=DRAFT,
                                     editable=False)
    budget_version = models.PositiveSmallIntegerField(_("budget version"), default=1, editable=False)
    approved_total = models.DecimalField(_("approved budget (EGP)"), max_digits=14, decimal_places=2, default=0,
                                         editable=False)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("submitted by"), null=True, editable=False, related_name="+",
                                     on_delete=models.SET_NULL)

    class Meta:
        verbose_name = _("project budget and profile")
        verbose_name_plural = _("project budgets and profiles")
        ordering = ["project__code"]
        permissions = [("view_all_projects", _("Can see every project (not only own)"))]

    def __str__(self):
        return str(self.project)

    @property
    def locked(self):
        return self.budget_status in (self.PENDING, self.APPROVED)

    def total(self):
        return self.lines.aggregate(s=Sum("amount"))["s"] or ZERO

    # ---- maker-checker on the budget
    approval_doc_type = "projects.budget"

    def approval_title(self):
        return f"{_('Project budget')} {self.project.code} v{self.budget_version}"

    def approval_amount(self):
        return self.total()

    def _set(self, status, **extra):
        ProjectProfile.objects.filter(pk=self.pk).update(budget_status=status, **extra)
        self.budget_status = status
        for k, v in extra.items():
            setattr(self, k, v)

    def on_approval_submitted(self, request):
        if not self.lines.exists():
            raise ValidationError(_("Add budget lines before sending the budget for approval."))
        self._set(self.PENDING, submitted_by=request.maker)

    def on_approval_approved(self, request):
        self._set(self.APPROVED, approved_total=self.total())

    def on_approval_rejected(self, request):
        self._set(self.REJECTED)

    def on_approval_returned(self, request):
        self._set(self.RETURNED)

    def on_approval_cancelled(self, request):
        self._set(self.DRAFT)

    def reopen(self):
        """Start a revision: lines become editable again; the last approved total stays until re-approved."""
        if self.budget_status != self.APPROVED:
            raise ValidationError(_("Only an approved budget can be reopened for revision."))
        self._set(self.DRAFT, budget_version=self.budget_version + 1)


class BudgetLine(models.Model):
    profile = models.ForeignKey(ProjectProfile, related_name="lines", on_delete=models.CASCADE)
    account = models.ForeignKey("finance.Account", verbose_name=_("expense account"), on_delete=models.PROTECT,
                                limit_choices_to={"kind": "expense", "postable": True})
    description = models.CharField(_("description"), max_length=200, blank=True)
    amount = models.DecimalField(_("amount (EGP)"), max_digits=14, decimal_places=2,
                                 validators=[MinValueValidator(Decimal("0.01"))])
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        verbose_name = _("budget line")
        verbose_name_plural = _("budget lines")
        ordering = ["account__code"]

    def __str__(self):
        return f"{self.account} {self.amount}"

    def _check_open(self):
        if self.profile_id and ProjectProfile.objects.get(pk=self.profile_id).locked:
            raise ValidationError(_("The budget is awaiting approval or approved. Reopen it to revise."))

    def clean(self):
        if self.account_id and self.account.kind != "expense":
            raise ValidationError({"account": _("Budget lines use expense accounts.")})
        self._check_open()

    def save(self, *args, **kwargs):
        self._check_open()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._check_open()
        return super().delete(*args, **kwargs)


class Milestone(models.Model):
    project = models.ForeignKey(Project, verbose_name=_("project"), related_name="milestones", on_delete=models.CASCADE)
    title = models.CharField(_("title"), max_length=200)
    due = models.DateField(_("due date"), null=True, blank=True)

    class Meta:
        verbose_name = _("milestone")
        verbose_name_plural = _("milestones")
        ordering = ["due", "id"]

    def __str__(self):
        return self.title

    def progress(self):
        return weighted_progress(self.tasks.all())


class Task(models.Model):
    TODO, DOING, DONE, BLOCKED = "todo", "doing", "done", "blocked"
    STATUSES = [(TODO, _("To do")), (DOING, _("In progress")), (DONE, _("Done")), (BLOCKED, _("Blocked"))]

    project = models.ForeignKey(Project, verbose_name=_("project"), related_name="tasks", on_delete=models.CASCADE)
    milestone = models.ForeignKey(Milestone, verbose_name=_("milestone"), null=True, blank=True,
                                  related_name="tasks", on_delete=models.SET_NULL)
    title = models.CharField(_("title"), max_length=200)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("assigned to"), null=True, blank=True,
                                 related_name="project_tasks", on_delete=models.SET_NULL)
    start = models.DateField(_("start"), null=True, blank=True)
    due = models.DateField(_("due date"), null=True, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=TODO)
    percent = models.PositiveSmallIntegerField(_("% complete"), default=0, validators=[MaxValueValidator(100)])
    weight = models.PositiveSmallIntegerField(_("weight"), default=1,
                                              help_text=_("How much this task counts in the project's progress."))

    class Meta:
        verbose_name = _("task")
        verbose_name_plural = _("tasks")
        ordering = ["due", "id"]

    def __str__(self):
        return self.title

    def clean(self):
        if self.milestone_id and self.milestone.project_id != self.project_id:
            raise ValidationError({"milestone": _("The milestone belongs to another project.")})
        if self.start and self.due and self.due < self.start:
            raise ValidationError({"due": _("The due date is before the start date.")})

    def save(self, *args, **kwargs):
        if self.status == self.DONE:
            self.percent = 100
        super().save(*args, **kwargs)


def weighted_progress(tasks):
    total = done = 0
    for t in tasks:
        total += t.weight
        done += t.weight * t.percent
    return round(done / total) if total else 0
