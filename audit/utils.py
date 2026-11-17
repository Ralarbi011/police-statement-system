from .middleware import get_current_request
from .models import AuditLog


def client_ip(request):
    # Only trust X-Forwarded-For when behind your own reverse proxy (nginx/IIS).
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(action, obj=None, details="", user=None, request=None, username=None):
    request = request or get_current_request()
    if user is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        user = request.user
    entry = AuditLog(
        user=user,
        username=username or (user.username if user else ""),
        station_code=(user.station.code if user and getattr(user, "station", None) else ""),
        action=action,
        details=details[:5000],
    )
    if obj is not None:
        entry.object_type = obj.__class__.__name__
        entry.object_id = str(obj.pk)
        entry.object_repr = str(obj)[:255]
    if request is not None:
        entry.ip_address = client_ip(request)
        entry.user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]
    entry.save()
    return entry
