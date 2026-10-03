from django.core.management.base import BaseCommand

from common.models import ImportantNotice


NOTICE_KEY = "attendance-session-policy-2026-08"
NOTICE_TITLE = "Important: New Attendance and Session Policy"
NOTICE_BODY = """OceanClouds ERP now uses a fixed login session.

If you do not log out, your session will expire automatically and any active task will be paused at the session deadline.

A missed logout appears under My Attendance & Leave as Missing Checkout. Submit your actual checkout time and the reason. Your project manager will approve or reject the request. If rejected, you may correct it and submit it again.

Attendance is counted only from completed or approved login time. Leave requests are also available from the Attendance & Leave page.

Please remember to stop active tasks and log out when your workday is complete."""


class Command(BaseCommand):
    help = "Publish or refresh the mandatory attendance and session policy notice."

    def handle(self, *args, **options):
        notice, created = ImportantNotice.objects.update_or_create(
            key=NOTICE_KEY,
            defaults={
                "title": NOTICE_TITLE,
                "body": NOTICE_BODY,
                "is_active": True,
                "requires_acknowledgement": True,
            },
        )
        action = "Published" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} notice: {notice.title}"))
