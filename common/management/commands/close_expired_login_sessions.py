from django.core.management.base import BaseCommand

from common.session_management import close_expired_login_sessions


class Command(BaseCommand):
    help = "Close login sessions that reached their fixed deadline."

    def handle(self, *args, **options):
        closed_keys = close_expired_login_sessions()
        if options["verbosity"]:
            self.stdout.write(f"Closed {len(closed_keys)} expired login session(s).")
