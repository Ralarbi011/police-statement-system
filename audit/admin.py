from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: nobody, including administrators, may change or delete entries."""

    list_display = ("timestamp", "username", "station_code", "action", "object_type", "object_id", "object_repr", "ip_address")
    list_filter = ("action", "object_type", "station_code")
    search_fields = ("username", "object_id", "object_repr", "details", "ip_address")
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
