import csv
import io

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from approvals import services
from core.admin import AttachmentInline, stamp_attachments

from . import payroll
from .models import (Appraisal, Assignment, Contract, Employee, EmployeePayItem, Grade, Incentive, InsuranceRule,
                     PayComponent, PayrollRun, Payslip, Position, TaxBracket)


def can_see_pay(request):
    return request.user.has_perm("hr.view_salary")


class SalaryAware:
    """Hide money fields from users without the 'view salaries' permission."""

    salary_fields = ()

    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or [])
        return excluded if can_see_pay(request) else excluded + list(self.salary_fields)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        return fields if can_see_pay(request) else [f for f in fields if f not in self.salary_fields]

    def get_list_display(self, request):
        cols = super().get_list_display(request)
        return cols if can_see_pay(request) else [c for c in cols if c not in self.salary_fields]


def send_for_approval(modeladmin, request, queryset):
    for obj in queryset:
        try:
            services.submit(obj, request.user)
            modeladmin.message_user(request, f"{obj}: ✓", messages.SUCCESS)
        except (services.ApprovalError, ValidationError) as exc:
            msg = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            modeladmin.message_user(request, f"{obj}: {msg}", messages.ERROR)


send_for_approval.short_description = _("Send for approval")


@admin.register(Grade)
class GradeAdmin(SalaryAware, admin.ModelAdmin):
    list_display = ("code", "name_ar", "level", "min_salary", "max_salary")
    salary_fields = ("min_salary", "max_salary")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "department", "grade", "reports_to", "headcount", "filled", "is_active")
    list_filter = ("department", "is_active")
    search_fields = ("code", "name_ar", "name_en")


class ContractInline(SalaryAware, admin.TabularInline):
    model = Contract
    extra = 0
    fields = ("contract_type", "start_date", "end_date", "probation_end", "basic_salary", "status")
    salary_fields = ("basic_salary",)


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0


class PayItemInline(admin.TabularInline):
    model = EmployeePayItem
    extra = 0

    def has_view_permission(self, request, obj=None):
        return can_see_pay(request) and super().has_view_permission(request, obj)


@admin.register(Employee)
class EmployeeAdmin(SalaryAware, admin.ModelAdmin):
    list_display = ("employee_no", "name_ar", "department", "position", "grade", "hire_date", "status")
    list_filter = ("status", "department", "grade")
    search_fields = ("employee_no", "name_ar", "name_en", "national_id", "phone")
    readonly_fields = ("employee_no",)
    autocomplete_fields = ("manager", "position", "user")
    inlines = [ContractInline, AssignmentInline, PayItemInline, AttachmentInline]
    salary_fields = ("bank_name", "bank_account")

    def save_formset(self, request, form, formset, change):
        if formset.model.__name__ == "Attachment":
            stamp_attachments(request, formset)
        else:
            formset.save()


@admin.register(Contract)
class ContractAdmin(SalaryAware, admin.ModelAdmin):
    list_display = ("contract_no", "employee", "contract_type", "start_date", "end_date", "basic_salary", "status")
    list_filter = ("contract_type", "status")
    search_fields = ("contract_no", "employee__name_ar", "employee__employee_no")
    autocomplete_fields = ("employee",)
    inlines = [AttachmentInline]
    salary_fields = ("basic_salary",)

    def save_formset(self, request, form, formset, change):
        stamp_attachments(request, formset)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("employee", "department", "project", "percent", "start_date", "end_date")
    list_filter = ("department", "project")
    autocomplete_fields = ("employee",)


@admin.register(PayComponent)
class PayComponentAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "kind", "taxable", "insurable")


@admin.register(Incentive)
class IncentiveAdmin(admin.ModelAdmin):
    list_display = ("employee", "kind", "amount", "pay_month", "pay_year", "status", "reason")
    list_filter = ("status", "kind", "pay_year")
    autocomplete_fields = ("employee",)
    readonly_fields = ("status", "requested_by")
    actions = [send_for_approval]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.requested_by = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj)
        return allowed and (obj is None or obj.status in (Incentive.DRAFT, Incentive.RETURNED))


@admin.register(InsuranceRule)
class InsuranceRuleAdmin(admin.ModelAdmin):
    list_display = ("year", "employee_rate", "employer_rate", "min_insurable", "max_insurable", "verified_by")


@admin.register(TaxBracket)
class TaxBracketAdmin(admin.ModelAdmin):
    list_display = ("year", "lower", "upper", "rate", "annual_exemption")
    list_filter = ("year",)


class PayslipInline(admin.TabularInline):
    model = Payslip
    extra = 0
    can_delete = False
    fields = ("employee", "days_paid", "basic", "gross", "insurance_employee", "income_tax", "net", "employer_cost",
              "print_link")
    readonly_fields = fields

    @admin.display(description=_("Payslip"))
    def print_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        return format_html('<a href="{}" target="_blank">🖶</a>', reverse("payslip", args=[obj.pk])) if obj.pk else ""

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "total_gross", "total_net", "total_cost", "prepared_by", "calculated_at")
    readonly_fields = ("status", "total_gross", "total_net", "total_cost", "prepared_by", "calculated_at")
    inlines = [PayslipInline]
    actions = ["calculate", send_for_approval, "bank_file", "mark_paid"]

    def has_module_permission(self, request):
        return can_see_pay(request) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return can_see_pay(request) and super().has_view_permission(request, obj)

    @admin.action(description=_("Calculate payroll"))
    def calculate(self, request, queryset):
        if not request.user.has_perm("hr.run_payroll"):
            self.message_user(request, _("You are not allowed to prepare payroll."), messages.ERROR)
            return
        for run in queryset:
            try:
                payroll.calculate(run, request.user)
                self.message_user(request, f"{run}: ✓", messages.SUCCESS)
            except payroll.PayrollError as exc:
                self.message_user(request, f"{run}: {exc}", messages.ERROR)

    @admin.action(description=_("Download bank transfer file (approved runs)"))
    def bank_file(self, request, queryset):
        runs = [r for r in queryset if r.status in (PayrollRun.APPROVED, PayrollRun.PAID)]
        if not runs:
            self.message_user(request, _("Only approved payroll can be paid."), messages.ERROR)
            return None
        buf = io.StringIO()
        buf.write("﻿")
        w = csv.writer(buf)
        w.writerow(["employee_no", "name", "bank", "account", "net", "period"])
        for run in runs:
            for s in run.payslips.select_related("employee"):
                w.writerow([s.employee.employee_no, s.employee.name_ar, s.bank_name, s.bank_account, s.net, str(run)])
        from core.audit import log_event
        for run in runs:
            log_event("bank_file", run)
        response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = "attachment; filename=payroll-bank-file.csv"
        return response

    @admin.action(description=_("Mark as paid"))
    def mark_paid(self, request, queryset):
        for run in queryset.filter(status=PayrollRun.APPROVED):
            run._set(PayrollRun.PAID)


@admin.register(Appraisal)
class AppraisalAdmin(admin.ModelAdmin):
    list_display = ("employee", "period_start", "period_end", "reviewer", "rating", "status")
    list_filter = ("status", "rating")
    autocomplete_fields = ("employee", "reviewer")
