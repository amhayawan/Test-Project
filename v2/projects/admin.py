from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from approvals import services
from core.models import Project

from .models import BudgetLine, Milestone, ProjectProfile, Task
from .services import visible_projects


def _error(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


class ScopedToProjects:
    """Project managers only see and pick their own projects."""

    project_path = "project"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(**{f"{self.project_path}__in": visible_projects(request.user)})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.related_model is Project:
            kwargs["queryset"] = visible_projects(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class BudgetLineInline(admin.TabularInline):
    model = BudgetLine
    extra = 1
    fields = ("account", "description", "amount", "fund")

    def _open(self, obj):
        return obj is None or not obj.locked

    def has_add_permission(self, request, obj=None):
        return self._open(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._open(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._open(obj) and super().has_delete_permission(request, obj)


@admin.register(ProjectProfile)
class ProjectProfileAdmin(ScopedToProjects, admin.ModelAdmin):
    list_display = ("project", "budget_status", "budget_version", "approved_total", "draft_total", "location")
    list_filter = ("budget_status",)
    search_fields = ("project__code", "project__name_ar", "grant_reference")
    readonly_fields = ("budget_status", "budget_version", "approved_total", "submitted_by")
    inlines = [BudgetLineInline]
    actions = ["send_budget", "reopen_budget"]

    @admin.display(description=_("budget lines total"))
    def draft_total(self, obj):
        return f"{obj.total():,.2f}"

    @admin.action(description=_("Send budget for approval"))
    def send_budget(self, request, queryset):
        for p in queryset:
            try:
                services.submit(p, request.user)
                self.message_user(request, f"{p}: ✓", messages.SUCCESS)
            except (services.ApprovalError, ValidationError) as exc:
                self.message_user(request, f"{p}: {_error(exc)}", messages.ERROR)

    @admin.action(description=_("Reopen approved budget for revision"))
    def reopen_budget(self, request, queryset):
        for p in queryset:
            try:
                p.reopen()
                self.message_user(request, f"{p}: v{p.budget_version}", messages.SUCCESS)
            except ValidationError as exc:
                self.message_user(request, f"{p}: {_error(exc)}", messages.ERROR)


@admin.register(Milestone)
class MilestoneAdmin(ScopedToProjects, admin.ModelAdmin):
    list_display = ("title", "project", "due")
    list_filter = ("project",)


@admin.register(Task)
class TaskAdmin(ScopedToProjects, admin.ModelAdmin):
    list_display = ("title", "project", "milestone", "assignee", "start", "due", "status", "percent", "weight")
    list_filter = ("status", "project")
    search_fields = ("title",)
    list_editable = ("status", "percent")
