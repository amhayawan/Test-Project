"""Helpers for modules' seed.py files."""
from django.contrib.auth.models import Group


def policy(doc_type, min_amount, roles):
    """Create an approval policy with steps in order, unless one already exists (never overwrites edits)."""
    from approvals.models import ApprovalPolicy, ApprovalStep
    obj, created = ApprovalPolicy.objects.get_or_create(doc_type=doc_type, min_amount=min_amount)
    if created:
        for order, role in enumerate(roles, start=1):
            ApprovalStep.objects.create(policy=obj, order=order, role=Group.objects.get(name=role))
    return obj
