import secrets
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


class BilingualName(models.Model):
    """Arabic name is official and required; English is optional."""

    name_ar = models.CharField(_("name (Arabic)"), max_length=160)
    name_en = models.CharField(_("name (English)"), max_length=160, blank=True)

    class Meta:
        abstract = True

    @property
    def name(self):
        if (get_language() or "ar").startswith("en") and self.name_en:
            return self.name_en
        return self.name_ar

    def __str__(self):
        return self.name


class Branch(BilingualName):
    code = models.CharField(_("code"), max_length=20, unique=True)
    address = models.CharField(_("address"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("branch")
        verbose_name_plural = _("branches")
        ordering = ["code"]


class Department(BilingualName):
    """Departments double as cost centres: every cost is posted to one."""

    code = models.CharField(_("cost centre code"), max_length=20, unique=True)
    branch = models.ForeignKey(Branch, verbose_name=_("branch"), null=True, blank=True, on_delete=models.PROTECT)
    parent = models.ForeignKey("self", verbose_name=_("parent department"), null=True, blank=True,
                               on_delete=models.PROTECT, related_name="children")
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("manager"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="managed_departments")
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("department / cost centre")
        verbose_name_plural = _("departments / cost centres")
        ordering = ["code"]


class Fund(BilingualName):
    """Where money may be spent. Restricted funds (zakat, sponsorships, a project grant) are enforced."""

    UNRESTRICTED, RESTRICTED, ZAKAT = "unrestricted", "restricted", "zakat"
    KINDS = [(UNRESTRICTED, _("Unrestricted")), (RESTRICTED, _("Restricted")), (ZAKAT, _("Zakat"))]

    code = models.CharField(_("code"), max_length=20, unique=True)
    kind = models.CharField(_("type"), max_length=20, choices=KINDS, default=UNRESTRICTED)
    restriction = models.TextField(_("permitted uses"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("fund")
        verbose_name_plural = _("funds")
        ordering = ["code"]


class Project(BilingualName):
    PLANNED, ACTIVE, CLOSED = "planned", "active", "closed"
    STATUSES = [(PLANNED, _("Planned")), (ACTIVE, _("Active")), (CLOSED, _("Closed"))]

    code = models.CharField(_("code"), max_length=20, unique=True)
    department = models.ForeignKey(Department, verbose_name=_("department"), on_delete=models.PROTECT)
    fund = models.ForeignKey(Fund, verbose_name=_("fund"), null=True, blank=True, on_delete=models.PROTECT)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("manager"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="managed_projects")
    start_date = models.DateField(_("start date"), null=True, blank=True)
    end_date = models.DateField(_("end date"), null=True, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=PLANNED)

    class Meta:
        verbose_name = _("project")
        verbose_name_plural = _("projects")
        ordering = ["code"]


# ---------------------------------------------------------------- numbering

class Sequence(models.Model):
    """Official numbering per document type and year (receipts, vouchers, POs...). Never reused."""

    key = models.CharField(max_length=30)
    period = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("key", "period")]
        verbose_name = _("number sequence")
        verbose_name_plural = _("number sequences")

    def __str__(self):
        return f"{self.key} {self.period}: {self.last_value}"


SEQUENCE_FORMATS = {
    "receipt": "R-{period}-{n:05d}",
    "case": "C-{period}-{n:05d}",
    "aid": "A-{period}-{n:05d}",
    "employee": "E-{period}-{n:04d}",
    "contract": "HR-{period}-{n:04d}",
    "journal": "JV-{period}-{n:05d}",
    "payment": "PV-{period}-{n:05d}",
    "asset": "FA-{period}-{n:04d}",
    "purchase_request": "PR-{period}-{n:05d}",
    "purchase_order": "PO-{period}-{n:05d}",
    "goods_receipt": "GRN-{period}-{n:05d}",
    "supplier_invoice": "SI-{period}-{n:05d}",
    "stock_issue": "SIV-{period}-{n:05d}",
}


def next_number(key, period):
    """Atomically take the next number. Safe with several users saving at once."""
    with transaction.atomic():
        seq, _created = Sequence.objects.select_for_update().get_or_create(key=key, period=period)
        seq.last_value += 1
        seq.save(update_fields=["last_value"])
        fmt = SEQUENCE_FORMATS.get(key, key.upper() + "-{period}-{n:05d}")
        return fmt.format(period=period, n=seq.last_value)


# ---------------------------------------------------------------- attachments

ALLOWED_UPLOADS = {
    ".pdf": ("application/pdf", (b"%PDF",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".png": ("image/png", (b"\x89PNG",)),
}


def attachment_path(instance, filename):
    ext = Path(filename).suffix.lower()
    return f"attachments/{instance.content_type_id}/{instance.object_id}/{secrets.token_hex(16)}{ext}"


class Attachment(models.Model):
    """A file attached to any record (case documents, contracts, invoices...)."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    title = models.CharField(_("title"), max_length=160)
    doc_type = models.CharField(_("document type"), max_length=40, blank=True)
    file = models.FileField(_("file"), upload_to=attachment_path)
    original_name = models.CharField(max_length=255, blank=True)
    size = models.PositiveIntegerField(default=0)
    expires_on = models.DateField(_("expires on"), null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")
        indexes = [models.Index(fields=["content_type", "object_id"])]
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title

    @staticmethod
    def validate_upload(upload):
        """Return an error message, or None if the file is acceptable."""
        ext = Path(upload.name).suffix.lower()
        if ext not in ALLOWED_UPLOADS:
            return _("Allowed files: PDF, JPG or PNG.")
        head = upload.read(8)
        upload.seek(0)
        if not head.startswith(ALLOWED_UPLOADS[ext][1]):
            return _("The file content does not match its type.")
        if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            return _("The file is larger than %(mb)s MB.") % {"mb": settings.MAX_UPLOAD_MB}
        return None


# ---------------------------------------------------------------- audit trail

class AuditLog(models.Model):
    """Who did what and when. Append-only: the admin cannot edit or delete rows."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    username = models.CharField(max_length=150, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    action = models.CharField(max_length=30, db_index=True)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=40, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    summary = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("audit entry")
        verbose_name_plural = _("audit trail")
        ordering = ["-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.username} {self.action} {self.object_repr}"
