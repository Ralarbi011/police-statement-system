from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Station, User


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "region", "district", "is_active")
    list_filter = ("region", "is_active")
    search_fields = ("name", "code", "district")

    def has_delete_permission(self, request, obj=None):
        # Stations are referenced by cases; deactivate instead of deleting.
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "get_full_name", "service_number", "rank", "role", "station", "is_active", "last_login")
    list_filter = ("role", "station", "is_active")
    search_fields = ("username", "first_name", "last_name", "service_number")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Officer details", {"fields": ("first_name", "last_name", "email", "phone", "service_number", "rank")}),
        ("Access", {"fields": ("role", "station", "is_active")}),
        ("History", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": (
            "username", "password1", "password2", "first_name", "last_name",
            "service_number", "rank", "role", "station",
        )}),
    )
    readonly_fields = ("last_login", "date_joined")

    def has_delete_permission(self, request, obj=None):
        # Accounts are linked to statements and the audit trail.
        # Deactivate (untick "active") instead of deleting.
        return False
