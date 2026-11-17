from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = settings.SYSTEM_NAME
admin.site.site_title = "System Administration"
admin.site.index_title = "User, station and audit administration"

urlpatterns = [
    path("system-admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("records.urls")),
]

handler403 = "records.views.permission_denied"
