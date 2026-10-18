from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "name_ar", "name_en", "department", "is_active", "last_login")
    list_filter = ("is_active", "groups", "department")
    search_fields = ("username", "name_ar", "name_en", "email")
    fieldsets = BaseUserAdmin.fieldsets + (
        (_("Association"), {"fields": ("name_ar", "name_en", "language", "department",
                                       "scope_departments", "scope_projects")}),
    )
    filter_horizontal = ("groups", "user_permissions", "scope_departments", "scope_projects")
