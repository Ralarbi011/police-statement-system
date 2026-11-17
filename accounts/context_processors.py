from django.conf import settings


def system_info(request):
    return {"SYSTEM_NAME": settings.SYSTEM_NAME}
