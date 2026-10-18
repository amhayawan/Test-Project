from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

# Document types are registered by each module (see approvals.registry); no DB choices, so a new
# module can add its own types without a migration here.
from .registry import doc_type_label  # noqa: E402


class ApprovalPolicy(models.Model):
    """Who must approve a document type, optionally depending on the amount.

    The policy with the highest min_amount that is <= the document amount applies.
    """

    doc_type = models.CharField(_("document type"), max_length=40)
    min_amount = models.DecimalField(_("from amount"), max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(_("active"), default=True)

    def get_doc_type_display(self):
        return doc_type_label(self.doc_type)

    class Meta:
        verbose_name = _("approval policy")
        verbose_name_plural = _("approval policies")
        unique_together = [("doc_type", "min_amount")]
        ordering = ["doc_type", "min_amount"]

    def __str__(self):
        return f"{self.get_doc_type_display()} ≥ {self.min_amount:,.0f}"


class ApprovalStep(models.Model):
    policy = models.ForeignKey(ApprovalPolicy, related_name="steps", on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(_("order"))
    role = models.ForeignKey(Group, verbose_name=_("approver role"), on_delete=models.PROTECT)

    class Meta:
        ordering = ["order"]
        unique_together = [("policy", "order")]
        verbose_name = _("approval step")
        verbose_name_plural = _("approval steps")

    def __str__(self):
        return f"{self.order}. {self.role_label}"

    @property
    def role_label(self):
        from accounts.roles import role_label
        return role_label(self.role.name)


class ApprovalRequest(models.Model):
    PENDING, APPROVED, REJECTED, RETURNED, CANCELLED = "pending", "approved", "rejected", "returned", "cancelled"
    STATUSES = [(PENDING, _("Pending")), (APPROVED, _("Approved")), (REJECTED, _("Rejected")),
                (RETURNED, _("Returned for changes")), (CANCELLED, _("Cancelled"))]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    document = GenericForeignKey("content_type", "object_id")
    doc_type = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    policy = models.ForeignKey(ApprovalPolicy, on_delete=models.PROTECT)
    maker = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="+", on_delete=models.PROTECT)
    maker_note = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    current_step = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def get_doc_type_display(self):
        return doc_type_label(self.doc_type)

    class Meta:
        verbose_name = _("approval request")
        verbose_name_plural = _("approval requests")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return self.title

    @property
    def step(self):
        return self.policy.steps.filter(order=self.current_step).first()


class ApprovalAction(models.Model):
    APPROVE, REJECT, RETURN = "approve", "reject", "return"
    DECISIONS = [(APPROVE, _("Approve")), (REJECT, _("Reject")), (RETURN, _("Return for changes"))]

    request = models.ForeignKey(ApprovalRequest, related_name="actions", on_delete=models.CASCADE)
    step_order = models.PositiveSmallIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=10, choices=DECISIONS)
    comment = models.TextField(blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at"]
