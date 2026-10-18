"""Automatic audit trail.

Models listed via `track(Model)` get a row for every create / update / delete with the
old and new value of each changed field. Explicit events (login, approvals...) use log_event().
"""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save, pre_save

from .middleware import current_request, current_user

_tracked = {}


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value if isinstance(value, (str, int, float, bool, type(None))) else str(value)


def _snapshot(instance, exclude):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in exclude:
            continue
        data[field.name] = _plain(getattr(instance, field.attname))
    return data


def _client_ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR")


def log_event(action, obj=None, summary="", changes=None, request=None, user=None):
    from .models import AuditLog
    request = request or current_request()
    user = user or (request.user if request is not None and getattr(request, "user", None)
                    and request.user.is_authenticated else current_user())
    AuditLog.objects.create(
        user=user, username=getattr(user, "username", "") or "",
        ip=_client_ip(request), action=action,
        content_type=ContentType.objects.get_for_model(obj) if obj is not None else None,
        object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
        object_repr=str(obj)[:200] if obj is not None else "",
        changes=changes or {}, summary=str(summary)[:500],
    )


def _pre_save(sender, instance, **kwargs):
    exclude = _tracked[sender]
    if instance.pk:
        old = sender._base_manager.filter(pk=instance.pk).first()
        instance._audit_before = _snapshot(old, exclude) if old else None
    else:
        instance._audit_before = None


def _post_save(sender, instance, created, **kwargs):
    exclude = _tracked[sender]
    after = _snapshot(instance, exclude)
    if created:
        log_event("create", instance, changes={k: [None, v] for k, v in after.items() if v not in (None, "")})
        return
    before = getattr(instance, "_audit_before", None) or {}
    diff = {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}
    if diff:
        log_event("update", instance, changes=diff)


def _post_delete(sender, instance, **kwargs):
    log_event("delete", instance, changes={k: [v, None] for k, v in _snapshot(instance, _tracked[sender]).items()})


def track(model, exclude=("password", "last_login")):
    _tracked[model] = set(exclude)
    uid = f"audit-{model._meta.label}"
    pre_save.connect(_pre_save, sender=model, dispatch_uid=uid + "-pre")
    post_save.connect(_post_save, sender=model, dispatch_uid=uid + "-post")
    post_delete.connect(_post_delete, sender=model, dispatch_uid=uid + "-del")
    return model
