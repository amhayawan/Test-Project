from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from . import registry
from .models import ApprovalAction, ApprovalPolicy, ApprovalRequest, ApprovalStep


class PolicyForm(forms.ModelForm):
    doc_type = forms.ChoiceField(label=_("document type"), choices=registry.choices)

    class Meta:
        model = ApprovalPolicy
        fields = "__all__"


class StepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 1


@admin.register(ApprovalPolicy)
class ApprovalPolicyAdmin(admin.ModelAdmin):
    form = PolicyForm
    list_display = ("doc_type_label", "min_amount", "is_active")
    inlines = [StepInline]

    @admin.display(description=_("document type"))
    def doc_type_label(self, obj):
        return obj.get_doc_type_display()


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
