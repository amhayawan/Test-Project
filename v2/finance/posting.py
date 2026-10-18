"""Automatic journal entries from other modules' business events.

* Each (document, event) has at most one live entry. If the document changes, the old entry is
  reversed and a new one posted, so history is never edited and the ledger always matches.
* If an entry cannot be made (missing posting rule, locked month), the other module's work is NOT
  blocked: the problem is queued under Finance → Posting problems, and can be retried after fixing.

Modules register builders:  register("aid.delivered", build_aid)
A builder returns None (nothing to book) or a dict:
    {"date": date, "description": str, "source": "aid",
     "lines": [{"account": Account, "debit": x, "credit": y, "fund": Fund, "project": Project,
                "department": Department, "memo": str}, ...]}
"""
from datetime import date as date_cls

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import ZERO, FinanceError, JournalEntry, JournalLine, PostingIssue, money

BUILDERS = {}


def register(event, builder):
    BUILDERS[event] = builder


def _signature(day, lines):
    return (day, sorted((l["account"].pk, money(l.get("debit")), money(l.get("credit")),
                         getattr(l.get("fund"), "pk", None), getattr(l.get("project"), "pk", None),
                         getattr(l.get("department"), "pk", None)) for l in lines))


def _clean(lines):
    """Round, net each line to one side (a negative debit is a credit), drop zero lines."""
    out = []
    for l in lines:
        net = money(l.get("debit")) - money(l.get("credit"))
        if net == 0:
            continue
        out.append({**l, "debit": net if net > 0 else ZERO, "credit": -net if net < 0 else ZERO})
    return out


def live_entry(document, event):
    ct = ContentType.objects.get_for_model(document)
    return (JournalEntry.objects.filter(source_type=ct, source_id=document.pk, source_event=event,
                                        status=JournalEntry.POSTED, reverses__isnull=True,
                                        reversed_by__isnull=True).first())


def _create(day, description, source, lines, document=None, event="", user=None, reverses=None):
    entry = JournalEntry(date=day, description=description[:255], source=source, created_by=user, reverses=reverses)
    if document is not None:
        entry.source_type = ContentType.objects.get_for_model(document)
        entry.source_id = document.pk
        entry.source_event = event
    entry.save()
    JournalLine.objects.bulk_create([
        JournalLine(entry=entry, account=l["account"], debit=l["debit"], credit=l["credit"], fund=l.get("fund"),
                    project=l.get("project"), department=l.get("department"), memo=(l.get("memo") or "")[:255])
        for l in lines])
    return entry


def reverse(entry, user=None, day=None, post=True):
    """Reversing entry. Automatic corrections post at once; a manual reversal goes for approval (post=False)."""
    if entry.status != JournalEntry.POSTED:
        raise FinanceError(_("Only a posted entry can be reversed."))
    if hasattr(entry, "reversed_by"):
        raise FinanceError(_("This entry has already been reversed."))
    lines = [{"account": l.account, "debit": l.credit, "credit": l.debit, "fund": l.fund, "project": l.project,
              "department": l.department, "memo": l.memo} for l in entry.lines.all()]
    rev = _create(day or max(entry.date, timezone.localdate()), _("Reversal of %(no)s") % {"no": entry.entry_no},
                  "reversal", lines, entry.source_document, entry.source_event, user, reverses=entry)
    if post:
        rev.post()
    return rev


@transaction.atomic
def book(document, event, spec, user=None):
    """Make the ledger match what `spec` says for this document and event."""
    old = live_entry(document, event)
    lines = _clean(spec["lines"]) if spec else []
    if old is not None:
        old_lines = [{"account": l.account, "debit": l.debit, "credit": l.credit, "fund": l.fund,
                      "project": l.project, "department": l.department} for l in old.lines.all()]
        if spec and _signature(spec["date"], lines) == _signature(old.date, old_lines):
            return old
        reverse(old, user, day=spec["date"] if spec else None)
    if not lines:
        return None
    entry = _create(spec["date"], spec["description"], spec["source"], lines, document, event, user)
    entry.post()
    return entry


def _jsonable(extra):
    return {k: (v.isoformat() if isinstance(v, date_cls) else v) for k, v in extra.items()
            if isinstance(v, (str, int, float, bool, date_cls)) or v is None}


def handle(event, document, user=None, **extra):
    builder = BUILDERS.get(event)
    if builder is None or document.pk is None:
        return None
    ct = ContentType.objects.get_for_model(document)
    try:
        with transaction.atomic():
            entry = book(document, event, builder(document, **extra), user)
    except (FinanceError, ValidationError) as exc:
        msg = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        PostingIssue.objects.update_or_create(
            event=event, source_type=ct, source_id=document.pk, resolved_at=None,
            defaults={"message": msg, "extra": _jsonable(extra)})
        return None
    PostingIssue.objects.filter(event=event, source_type=ct, source_id=document.pk, resolved_at=None) \
        .update(resolved_at=timezone.now())
    return entry


def retry(issue):
    document = issue.source_document
    if document is None:            # the source was deleted: nothing left to book
        PostingIssue.objects.filter(pk=issue.pk).update(resolved_at=timezone.now())
        return None
    extra = {k: (date_cls.fromisoformat(v) if k in ("day",) and isinstance(v, str) else v)
             for k, v in (issue.extra or {}).items()}
    handle(issue.event, document, **extra)
    issue.refresh_from_db()
    return issue.resolved_at is not None


def on_business_event(sender, event, document, **extra):
    handle(event, document, **extra)
