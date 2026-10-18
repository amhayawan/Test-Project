from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from approvals import services
from core.audit import log_event
from core.models import Attachment, Department

from . import leave
from .models import Employee, LeaveRequest, LeaveType, Payslip, PayrollRun, Position


@login_required
@permission_required("hr.view_position", raise_exception=True)
def structure(request):
    """Departments → positions (approved headcount vs filled) → people."""
    rows = []
    for dept in Department.objects.filter(is_active=True).prefetch_related("positions__employees"):
        positions = []
        for pos in dept.positions.filter(is_active=True):
            people = [e for e in pos.employees.all() if e.status != Employee.TERMINATED]
            positions.append({"pos": pos, "people": people, "vacant": max(pos.headcount - len(people), 0)})
        unplaced = dept.employees.current().filter(position__isnull=True)
        rows.append({"dept": dept, "positions": positions, "unplaced": unplaced,
                     "headcount": sum(p["pos"].headcount for p in positions),
                     "filled": dept.employees.current().count()})
    return render(request, "hr/structure.html", {"rows": rows})


@login_required
def payslip(request, pk):
    slip = get_object_or_404(Payslip.objects.select_related("run", "employee__department", "employee__position"), pk=pk)
    own = slip.employee.user_id == request.user.pk
    if not (request.user.has_perm("hr.view_salary") or own):
        raise Http404
    if own and slip.run.status not in (PayrollRun.APPROVED, PayrollRun.PAID):
        raise Http404            # employees see their payslip only once payroll is approved
    log_event("payslip_view", slip.run, summary=slip.employee.employee_no)
    earnings = [l for l in slip.lines if l["kind"] == "earning"]
    deductions = [l for l in slip.lines if l["kind"] != "earning"]
    return render(request, "hr/payslip.html", {"s": slip, "earnings": earnings, "deductions": deductions})


@login_required
def my_payslips(request):
    emp = getattr(request.user, "employee", None)
    slips = (Payslip.objects.filter(employee=emp, run__status__in=(PayrollRun.APPROVED, PayrollRun.PAID))
             .select_related("run") if emp else [])
    return render(request, "hr/my_payslips.html", {"slips": slips, "employee": emp})


# ---------------------------------------------------------------- self-service leave

class LeaveForm(forms.ModelForm):
    document = forms.FileField(label=_("Supporting document (PDF, JPG or PNG)"), required=False)

    class Meta:
        model = LeaveRequest
        fields = ["leave_type", "start_date", "end_date", "hours", "reason"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}),
                   "end_date": forms.DateInput(attrs={"type": "date"}),
                   "hours": forms.NumberInput(attrs={"step": "0.5", "min": "0.5"})}

    def __init__(self, *args, employee, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.employee = employee
        types = LeaveType.objects.filter(is_active=True, verified_at__isnull=False, verified_by__isnull=False)
        self.fields["leave_type"].queryset = types.filter(gender__in=("", employee.gender or "-"))

    def clean_document(self):
        upload = self.cleaned_data.get("document")
        if upload:
            problem = Attachment.validate_upload(upload)
            if problem:
                raise forms.ValidationError(problem)
        return upload

    def clean(self):
        data = super().clean()
        lt = data.get("leave_type")
        if lt and lt.needs_document and not data.get("document"):
            self.add_error("document", _("This leave type needs a supporting document."))
        return data


@login_required
def my_leave(request):
    emp = getattr(request.user, "employee", None)
    if emp is None:
        return render(request, "hr/my_leave.html", {"employee": None})
    today = timezone.localdate()
    form = LeaveForm(request.POST or None, request.FILES or None, employee=emp)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                req = form.save(commit=False)
                req.requested_by = request.user
                req.save()
                upload = form.cleaned_data.get("document")
                if upload:
                    Attachment.objects.create(
                        content_type=ContentType.objects.get_for_model(req), object_id=req.pk,
                        title=str(req.leave_type), doc_type="leave", file=upload,
                        original_name=upload.name[:255], size=upload.size, uploaded_by=request.user)
                services.submit(req, request.user)
        except (ValidationError, services.ApprovalError) as exc:
            for msg in (exc.messages if isinstance(exc, ValidationError) else [str(exc)]):
                form.add_error(None, msg)
        else:
            messages.success(request, _("Your request was sent to your manager for approval."))
            return redirect("my_leave")
    requests_ = list(emp.leave_requests.select_related("leave_type")[:50])
    for r in requests_:
        last = next(iter(services.history(r)), None)
        action = last.actions.last() if last else None
        r.decision_note = action.comment if action and r.status in (r.REJECTED, r.RETURNED) else ""
    return render(request, "hr/my_leave.html", {
        "employee": emp, "form": form, "requests": requests_, "year": today.year,
        "balances": leave.balances(emp, today.year, today)})


@login_required
@require_POST
def cancel_leave(request, pk):
    emp = getattr(request.user, "employee", None)
    req = get_object_or_404(LeaveRequest, pk=pk, employee=emp, status=LeaveRequest.PENDING) if emp else None
    if req is None:
        raise Http404
    try:
        services.cancel(req, request.user)
        messages.success(request, _("Request cancelled."))
    except services.ApprovalError as exc:
        messages.error(request, str(exc))
    return redirect("my_leave")
