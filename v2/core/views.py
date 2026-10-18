from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .audit import log_event
from .models import Attachment


def user_can_view_record(user, record):
    """Attachments inherit the access rules of the record they belong to."""
    meta = record._meta
    if not user.has_perm(f"{meta.app_label}.view_{meta.model_name}"):
        return False
    manager = type(record).objects
    if hasattr(manager, "visible_to"):
        return manager.visible_to(user).filter(pk=record.pk).exists()
    return True


@login_required
def attachment_download(request, pk):
    att = get_object_or_404(Attachment, pk=pk)
    if att.record is None or not user_can_view_record(request.user, att.record):
        raise Http404
    log_event("download", att.record, summary=att.title)
    return FileResponse(att.file.open("rb"), as_attachment=True, filename=att.original_name or att.file.name)
