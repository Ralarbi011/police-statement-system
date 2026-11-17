from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only record of who did what, when, and from where."""

    class Action(models.TextChoices):
        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"
        LOGIN_FAILED = "LOGIN_FAILED", "Failed login"
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        VIEW = "VIEW", "View"
        FINALIZE = "FINALIZE", "Finalize / lock"
        PRINT = "PRINT", "Print"
        DOWNLOAD = "DOWNLOAD", "Download"
        ASSIGN = "ASSIGN", "Assign"
        STATUS = "STATUS", "Status change"
        SEARCH = "SEARCH", "Search"

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="audit_entries",
    )
    username = models.CharField(max_length=150, blank=True, help_text="Kept even for failed logins.")
    station_code = models.CharField(max_length=12, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    object_type = models.CharField(max_length=50, blank=True)
    object_id = models.CharField(max_length=50, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("Audit log entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit log entries cannot be deleted.")

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.username} {self.action} {self.object_type} {self.object_id}"
