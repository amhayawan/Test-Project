from django.contrib import admin

from .models import ApprovalAction, ApprovalPolicy, ApprovalRequest, ApprovalStep


class StepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 1


@admin.register(ApprovalPolicy)
class ApprovalPolicyAdmin(admin.ModelAdmin):
    list_display = ("doc_type", "min_amount", "is_active")
    inlines = [StepInline]


class ActionInline(admin.TabularInline):
    model = ApprovalAction
    extra = 0
    can_delete = False
    readonly_fields = ("step_order", "actor", "decision", "comment", "at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "doc_type", "amount", "maker", "status", "current_step", "created_at")
    list_filter = ("status", "doc_type")
    readonly_fields = [f.name for f in ApprovalRequest._meta.fields]
    inlines = [ActionInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
