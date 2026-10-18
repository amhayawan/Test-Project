"""Leave rules: counting days, balances, limits, and the unpaid-leave deduction for payroll.

Nothing here contains a legal number. Every limit comes from the LeaveType and its yearly
balance lines, which HR enters and the labour-law specialist signs off.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.utils.translation import gettext as _

from .models import LeaveAdjustment, LeaveRequest, LeaveType, PayrollRun, PublicHoliday, money

ZERO = Decimal(0)


def plain(value):
    """10.00 -> '10', 2.50 -> '2.5' (Decimal.normalize alone would print 1E+1)."""
    return format(Decimal(value or 0).normalize(), "f")


def days_between(leave_type, start, end):
    """Days a leave of this type uses between two dates (inclusive)."""
    if end < start:
        return ZERO
    total = (end - start).days + 1
    if leave_type.calendar_days:
        return Decimal(total)
    holidays = set(PublicHoliday.objects.filter(date__range=(start, end)).values_list("date", flat=True))
    weekend = set(settings.WEEKEND_DAYS)
    return Decimal(sum(1 for i in range(total)
                       if (d := start + timedelta(days=i)).weekday() not in weekend and d not in holidays))


def count(req):
    if req.leave_type.unit == LeaveType.HOURS:
        return Decimal(req.hours or 0)
    return days_between(req.leave_type, req.start_date, req.end_date)


def service_months(emp, on):
    h = emp.hire_date
    return max((on.year - h.year) * 12 + on.month - h.month - (1 if on.day < h.day else 0), 0)


def age(emp, on):
    b = emp.birth_date
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day)) if b else None


def entitlement(emp, leave_type, on):
    """Yearly balance for this employee on a given date: the highest matching balance line."""
    months, years = service_months(emp, on), age(emp, on)
    best = ZERO
    for line in leave_type.entitlements.all():
        if months < line.min_service_months:
            continue
        if line.min_age and (years is None or years < line.min_age):
            continue
        best = max(best, line.days_per_year)
    return best


def _counting_for(emp, balance_type, year, exclude_pk=None):
    qs = LeaveRequest.objects.counting().filter(employee=emp, start_date__year=year).filter(
        Q(leave_type=balance_type) | Q(leave_type__deduct_from=balance_type))
    return qs.exclude(pk=exclude_pk) if exclude_pk else qs


def balance(emp, leave_type, year, on, exclude_pk=None):
    bt = leave_type.balance_type()
    entitled = entitlement(emp, bt, on)
    adjusted = LeaveAdjustment.objects.filter(employee=emp, leave_type=bt, year=year).aggregate(s=Sum("days"))["s"] or ZERO
    qs = _counting_for(emp, bt, year, exclude_pk)
    used = qs.filter(status=LeaveRequest.APPROVED).aggregate(s=Sum("amount"))["s"] or ZERO
    pending = qs.filter(status=LeaveRequest.PENDING).aggregate(s=Sum("amount"))["s"] or ZERO
    return {"type": bt, "entitled": entitled, "adjusted": adjusted, "used": used, "pending": pending,
            "available": entitled + adjusted - used - pending}


def balances(emp, year, on):
    types = LeaveType.objects.filter(is_active=True, deduct_from__isnull=True, entitlements__isnull=False).distinct()
    return [balance(emp, t, year, on) for t in types]


def _months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def validate(req, submitting=False):
    errors = {}

    def err(field, msg):
        errors.setdefault(field, []).append(msg)

    lt, emp = req.leave_type, req.employee
    if not (req.start_date and req.end_date and req.leave_type_id and req.employee_id):
        return
    if not lt.is_active or not lt.is_verified:
        err("leave_type", _("This leave type has not been signed off by the labour-law specialist yet."))
    if req.end_date < req.start_date:
        err("end_date", _("The end date is before the start date."))
    if req.start_date.year != req.end_date.year:
        err("end_date", _("Split leave that crosses the year end into two requests."))
    if lt.unit == LeaveType.HOURS:
        if req.start_date != req.end_date:
            err("end_date", _("A permission is for one day: use the same start and end date."))
        if not req.hours or req.hours <= 0:
            err("hours", _("Enter the number of hours."))
    elif req.hours:
        req.hours = None
    if lt.gender and emp.gender != lt.gender:
        err("leave_type", _("This leave type does not apply to this employee."))
    if req.start_date < emp.hire_date or (emp.end_date and req.end_date > emp.end_date):
        err("start_date", _("The dates are outside the employee's service."))
    if lt.min_service_months and service_months(emp, req.start_date) < lt.min_service_months:
        err("leave_type", _("Available only after %(n)s months of service.") % {"n": lt.min_service_months})
    if errors:
        raise ValidationError(errors)

    amount = count(req)
    req.amount = amount
    if amount <= 0:
        err("end_date", _("The chosen dates are all weekly rest days or official holidays."))
    if lt.max_per_request and amount > lt.max_per_request:
        err("end_date", _("At most %(n)s per request.") % {"n": plain(lt.max_per_request)})

    others = LeaveRequest.objects.counting().filter(employee=emp).exclude(pk=req.pk)
    clash = others.filter(start_date__lte=req.end_date, end_date__gte=req.start_date)
    if lt.unit == LeaveType.DAYS:
        if clash.exists():
            err("start_date", _("These dates overlap another leave request (%(t)s).") % {"t": clash.first().leave_type})
    elif clash.filter(leave_type__unit=LeaveType.DAYS).exists():
        err("start_date", _("The employee is already on leave that day."))

    same = others.filter(leave_type=lt)
    if lt.max_per_month:
        used = same.filter(start_date__year=req.start_date.year, start_date__month=req.start_date.month) \
            .aggregate(s=Sum("amount"))["s"] or ZERO
        if used + amount > lt.max_per_month:
            err("leave_type", _("Monthly limit is %(n)s; already used or requested: %(u)s.")
                % {"n": plain(lt.max_per_month), "u": plain(used)})
    if lt.max_per_year:
        used = same.filter(start_date__year=req.start_date.year).aggregate(s=Sum("amount"))["s"] or ZERO
        if used + amount > lt.max_per_year:
            err("leave_type", _("Yearly limit is %(n)s; already used or requested: %(u)s.")
                % {"n": plain(lt.max_per_year), "u": plain(used)})
    if lt.max_times_in_service and same.count() >= lt.max_times_in_service:
        err("leave_type", _("This leave can be taken at most %(n)s times during service.") % {"n": lt.max_times_in_service})

    bt = lt.balance_type()
    if bt.entitlements.exists():
        b = balance(emp, lt, req.start_date.year, req.start_date, exclude_pk=req.pk)
        if amount > b["available"]:
            err("end_date", _("Not enough %(type)s balance: %(a)s available, %(n)s requested.")
                % {"type": bt, "a": plain(b["available"]), "n": plain(amount)})

    if lt.paid_percent < 100:
        for y, m in _months(req.start_date, req.end_date):
            if PayrollRun.objects.filter(year=y, month=m, status__in=(PayrollRun.APPROVED, PayrollRun.PAID)).exists():
                err("start_date", _("Payroll for %(m)s/%(y)s is already approved; unpaid leave can no longer be "
                                    "recorded in that month.") % {"m": m, "y": y})
                break

    if submitting and lt.needs_document and req.pk:
        from core.models import Attachment
        ct = ContentType.objects.get_for_model(req)
        if not Attachment.objects.filter(content_type=ct, object_id=req.pk).exists():
            err("leave_type", _("Attach the supporting document (e.g. medical certificate) before sending."))
    if errors:
        raise ValidationError(errors)


def unpaid_lines(emp, start, end, monthly_basic, month_days):
    """Payroll deduction lines for approved leave paid below 100% inside one pay month."""
    lines = []
    reqs = (LeaveRequest.objects.filter(employee=emp, status=LeaveRequest.APPROVED, leave_type__paid_percent__lt=100,
                                        leave_type__unit=LeaveType.DAYS, start_date__lte=end, end_date__gte=start)
            .select_related("leave_type"))
    for r in reqs:
        lt = r.leave_type
        days = days_between(lt, max(start, r.start_date), min(end, r.end_date))
        value = money(monthly_basic * days / month_days * (100 - lt.paid_percent) / 100)
        if value > 0:
            lines.append({"code": "LEAVE", "name": f"{lt.name_ar} ({plain(days)})", "kind": "deduction",
                          "amount": str(value), "reduces_pay": True})
    return lines


def on_leave(day):
    return (LeaveRequest.objects.filter(status=LeaveRequest.APPROVED, leave_type__unit=LeaveType.DAYS,
                                        leave_type__nature=LeaveType.ABSENCE, start_date__lte=day, end_date__gte=day)
            .select_related("employee", "leave_type"))
