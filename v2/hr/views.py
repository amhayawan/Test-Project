from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from core.audit import log_event
from core.models import Department

from .models import Employee, Payslip, PayrollRun, Position


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
