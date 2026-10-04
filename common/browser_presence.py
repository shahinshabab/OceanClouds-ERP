"""Browser presence is an estimate, independent of attendance checkout."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def heartbeat_interval():
    return timedelta(seconds=settings.BROWSER_HEARTBEAT_INTERVAL_SECONDS)


def session_presence(login_session, now=None):
    now = now or timezone.now()
    offline_at = login_session.last_activity_at + timedelta(
        seconds=settings.BROWSER_OFFLINE_THRESHOLD_SECONDS
    )
    if login_session.logout_at or (
        login_session.expires_at and login_session.expires_at <= now
    ):
        status = "ended"
    else:
        status = "offline" if offline_at <= now else "online"
    return {
        "status": status,
        "last_seen_at": login_session.last_activity_at,
        "offline_since": offline_at if status == "offline" else None,
    }
