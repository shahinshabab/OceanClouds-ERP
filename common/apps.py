# common/apps.py

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "common"

    def ready(self):
        import common.signals  # noqa
        import common.live  # noqa
        from common.role_permissions import setup_role_groups

        post_migrate.connect(
            setup_role_groups,
            dispatch_uid="common.setup_role_groups",
        )
