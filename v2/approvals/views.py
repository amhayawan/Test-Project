from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .models import ApprovalRequest
from .services import ApprovalError, can_act, decide, inbox


@login_required
def inbox_view(request):
    mine = ApprovalRequest.objects.filter(maker=request.user).select_related("policy")[:30]
    return render(request, "approvals/inbox.html", {"waiting": inbox(request.user), "mine": mine})


@login_required
def request_view(request, pk):
    req = get_object_or_404(ApprovalRequest.objects.select_related("maker", "policy"), pk=pk)
    allowed = can_act(req, request.user)
    if not (allowed or req.maker_id == request.user.pk or req.actions.filter(actor=request.user).exists()
            or request.user.has_perm("approvals.view_approvalrequest")):
        raise Http404
    if request.method == "POST":
        try:
            decide(req, request.user, request.POST.get("decision"), request.POST.get("comment", ""))
            messages.success(request, req.get_status_display() if req.status != req.PENDING else "✓")
            return redirect("approvals_inbox")
        except (ApprovalError, ValidationError) as exc:
            messages.error(request, "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
            return redirect("approval_request", pk=pk)
    return render(request, "approvals/request.html", {"req": req, "can_act": allowed,
                                                      "actions": req.actions.select_related("actor")})
