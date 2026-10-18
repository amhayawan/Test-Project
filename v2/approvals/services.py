"""Maker-checker rules, enforced in code:

* the person who submits (maker) can never approve the same request;
* nobody can act twice on one request (each step needs a different person);
* only holders of the step's role may act, at the current step only;
* reject and return require a written reason;
* the document is told the outcome through on_approval_* hooks.

Documents that need approval implement (approval_excluded_user_ids() is optional):
    approval_doc_type: str          e.g. "cases.case"
    approval_title() -> str
    approval_amount() -> Decimal | None
    on_approval_submitted(request), on_approval_approved(request),
    on_approval_rejected(request), on_approval_returned(request)
"""
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import log_event

from .models import ApprovalAction, ApprovalPolicy, ApprovalRequest


class ApprovalError(Exception):
    pass


def policy_for(doc_type, amount):
    qs = ApprovalPolicy.objects.filter(doc_type=doc_type, is_active=True)
    if amount is not None:
        qs = qs.filter(min_amount__lte=amount)
    policy = qs.order_by("-min_amount").first()
    if not policy or not policy.steps.exists():
        raise ApprovalError(_("No approval policy is configured for this document. Ask the administrator."))
    return policy


def open_request(document):
    ct = ContentType.objects.get_for_model(document)
    return ApprovalRequest.objects.filter(content_type=ct, object_id=document.pk,
                                          status=ApprovalRequest.PENDING).first()


def history(document):
    ct = ContentType.objects.get_for_model(document)
    return ApprovalRequest.objects.filter(content_type=ct, object_id=document.pk).prefetch_related("actions")


@transaction.atomic
def submit(document, maker, note=""):
    if open_request(document):
        raise ApprovalError(_("This document is already waiting for approval."))
    amount = document.approval_amount()
    policy = policy_for(document.approval_doc_type, amount)
    req = ApprovalRequest.objects.create(
        content_type=ContentType.objects.get_for_model(document), object_id=document.pk,
        doc_type=document.approval_doc_type, title=document.approval_title()[:200], amount=amount,
        policy=policy, maker=maker, maker_note=note)
    document.on_approval_submitted(req)
    log_event("submit", document, summary=note)
    return req


def can_act(req, user):
    if req.status != ApprovalRequest.PENDING or not user.is_authenticated:
        return False
    if user.pk == req.maker_id:
        return False
    if req.actions.filter(actor=user).exists():
        return False
    document = req.document
    if document is not None and user.pk in getattr(document, "approval_excluded_user_ids", lambda: [])():
        return False      # e.g. whoever prepared a payroll may not approve it
    step = req.step
    return bool(step and (user.is_superuser or user.groups.filter(pk=step.role_id).exists()))


@transaction.atomic
def decide(req, user, decision, comment=""):
    req = ApprovalRequest.objects.select_for_update().get(pk=req.pk)
    if user.pk == req.maker_id:
        raise ApprovalError(_("You cannot approve a request you submitted yourself."))
    if not can_act(req, user):
        raise ApprovalError(_("You are not allowed to act on this request at this step."))
    comment = (comment or "").strip()
    if decision in (ApprovalAction.REJECT, ApprovalAction.RETURN) and not comment:
        raise ApprovalError(_("Write the reason for this decision."))
    if decision not in dict(ApprovalAction.DECISIONS):
        raise ApprovalError("invalid decision")
    ApprovalAction.objects.create(request=req, step_order=req.current_step, actor=user,
                                  decision=decision, comment=comment)
    document = req.document
    if decision == ApprovalAction.APPROVE and req.policy.steps.filter(order__gt=req.current_step).exists():
        req.current_step = req.policy.steps.filter(order__gt=req.current_step).first().order
        req.save(update_fields=["current_step"])
        log_event("approve_step", document, summary=comment)
        return req
    req.status = {ApprovalAction.APPROVE: req.APPROVED, ApprovalAction.REJECT: req.REJECTED,
                  ApprovalAction.RETURN: req.RETURNED}[decision]
    req.closed_at = timezone.now()
    req.save(update_fields=["status", "closed_at"])
    getattr(document, {req.APPROVED: "on_approval_approved", req.REJECTED: "on_approval_rejected",
                       req.RETURNED: "on_approval_returned"}[req.status])(req)
    log_event({req.APPROVED: "approve", req.REJECTED: "reject", req.RETURNED: "return"}[req.status],
              document, summary=comment)
    return req


def inbox(user):
    """Pending requests this user may act on now."""
    pending = ApprovalRequest.objects.filter(status=ApprovalRequest.PENDING).select_related("policy", "maker")
    return [r for r in pending if can_act(r, user)]
