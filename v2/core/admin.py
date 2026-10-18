from django import forms
from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline

from .models import Attachment, AuditLog, Branch, Department, Fund, Project, Sequence


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "name_en")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "name_en", "parent", "manager", "is_active")
    search_fields = ("code", "name_ar", "name_en")


@admin.register(Fund)
class FundAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "kind", "is_active")
    list_filter = ("kind",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ar", "department", "fund", "status", "start_date", "end_date")
    list_filter = ("status", "department")
    search_fields = ("code", "name_ar", "name_en")


@admin.register(Sequence)
class SequenceAdmin(admin.ModelAdmin):
    list_display = ("key", "period", "last_value")

    def has_change_permission(self, request, obj=None):
        return False  # numbers are never edited by hand

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("at", "username", "action", "content_type", "object_repr", "summary", "ip")
    list_filter = ("action", "content_type")
    search_fields = ("username", "object_repr", "summary")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ("title", "doc_type", "file", "expires_on")

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if upload and hasattr(upload, "content_type"):  # a newly uploaded file
            error = Attachment.validate_upload(upload)
            if error:
                raise forms.ValidationError(error)
        return upload


class AttachmentInline(GenericTabularInline):
    model = Attachment
    form = AttachmentForm
    extra = 0
    fields = ("title", "doc_type", "file", "expires_on", "uploaded_by", "uploaded_at")
    readonly_fields = ("uploaded_by", "uploaded_at")


def stamp_attachments(request, formset):
    """Record who uploaded each new attachment (call from ModelAdmin.save_formset)."""
    for obj in formset.save(commit=False):
        if isinstance(obj, Attachment) and not obj.pk:
            obj.uploaded_by = request.user
            obj.original_name = (obj.file.name or "")[:255]
            obj.size = obj.file.size
        obj.save()
    for obj in formset.deleted_objects:
        obj.delete()
    formset.save_m2m()
