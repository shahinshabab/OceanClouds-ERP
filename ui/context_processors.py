# ui/context_processors.py
from django.conf import settings

def app_version(request):
    return {
        "APP_VERSION": getattr(settings, "APP_VERSION", "dev"),
        "browser_heartbeat_interval_ms": settings.BROWSER_HEARTBEAT_INTERVAL_SECONDS * 1000,
        "browser_csrf_cookie_name": settings.CSRF_COOKIE_NAME,
    }
