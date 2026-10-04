# ui/context_processors.py
from django.conf import settings
from django.utils import timezone

def app_version(request):
    return {
        "APP_VERSION": getattr(settings, "APP_VERSION", "dev"),
        "browser_heartbeat_interval_ms": settings.BROWSER_HEARTBEAT_INTERVAL_SECONDS * 1000,
        "browser_csrf_cookie_name": settings.CSRF_COOKIE_NAME,
        "today": timezone.localdate(),
    }


def navigation(request):
    from ui.navigation import build_navigation

    sections = build_navigation(request)
    current = None
    for section in sections:
        for item in section["items"]:
            if item["active"]:
                current = {"section": section["title"], "label": item["label"], "url": item["url"]}
                break
        if current:
            break
    return {"nav_sections": sections, "nav_current": current}
