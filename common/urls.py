# common/urls.py

from django.urls import path
from .views import ImportantNoticeView, NotificationListView, mark_notification_read

app_name = "common"

urlpatterns = [
    path("notices/important/", ImportantNoticeView.as_view(), name="important_notice"),
    path("notifications/", NotificationListView.as_view(), name="notification_list"),
    path(
        "notifications/<int:pk>/mark-read/",
        mark_notification_read,
        name="notification_mark_read",
    ),
]
