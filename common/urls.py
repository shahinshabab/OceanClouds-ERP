# common/urls.py

from django.urls import path
from .views import ImportantNoticeView, NotificationListView, mark_notification_read, session_heartbeat

app_name = "common"

urlpatterns = [
    path("session/heartbeat/", session_heartbeat, name="session_heartbeat"),
    path("notices/important/", ImportantNoticeView.as_view(), name="important_notice"),
    path("notifications/", NotificationListView.as_view(), name="notification_list"),
    path(
        "notifications/<int:pk>/mark-read/",
        mark_notification_read,
        name="notification_mark_read",
    ),
]
