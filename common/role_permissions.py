from django.contrib.auth.models import Group, Permission
from django.db.models import Q

from common.roles import (
    ROLE_ADMIN,
    ROLE_CRM_MANAGER,
    ROLE_EMPLOYEE,
    ROLE_PROJECT_MANAGER,
)


LOCAL_APP_LABELS = [
    "adminpanel",
    "common",
    "crm",
    "events",
    "messaging",
    "projects",
    "reports",
    "sales",
    "services",
    "todos",
    "ui",
]


ROLE_DEFINITIONS = {
    ROLE_ADMIN: {
        "all_local_permissions": True,
    },
    ROLE_CRM_MANAGER: {
        "apps": {
            "common": ["view"],
            "crm": ["add", "change", "delete", "view"],
            "messaging": ["add", "change", "delete", "view"],
            "sales": ["add", "change", "delete", "view"],
            "todos": ["add", "change", "delete", "view"],
        },
    },
    ROLE_PROJECT_MANAGER: {
        "apps": {
            "common": ["view"],
            "crm": ["view"],
            "events": ["add", "change", "delete", "view"],
            "projects": ["add", "change", "delete", "view"],
            "sales": ["view"],
            "todos": ["add", "change", "delete", "view"],
        },
        "permissions": [
            ("common", "review_attendance"),
            ("common", "review_leave_requests"),
        ],
    },
    ROLE_EMPLOYEE: {
        "apps": {
            "common": ["view"],
            "events": ["view"],
            "projects": ["view"],
            "todos": ["add", "change", "view"],
        },
        "permissions": [
            ("common", "add_leaverequest"),
            ("common", "view_leaverequest"),
        ],
    },
}

LEGACY_ROLE_NAMES = ["Manager"]


def _permissions_for_actions(app_label, actions):
    query = Q()

    for action in actions:
        query |= Q(codename__startswith=f"{action}_")

    if not query:
        return Permission.objects.none()

    return Permission.objects.filter(
        query,
        content_type__app_label=app_label,
    )


def _permissions_for_role(definition):
    if definition.get("all_local_permissions"):
        return Permission.objects.filter(
            content_type__app_label__in=LOCAL_APP_LABELS,
        )

    permission_ids = set()

    for app_label, actions in definition.get("apps", {}).items():
        permission_ids.update(
            _permissions_for_actions(app_label, actions)
            .values_list("id", flat=True)
        )

    for app_label, codename in definition.get("permissions", []):
        permission_ids.update(
            Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename,
            ).values_list("id", flat=True)
        )

    return Permission.objects.filter(id__in=permission_ids)


def setup_role_groups(*args, **kwargs):
    Group.objects.filter(name__in=LEGACY_ROLE_NAMES).delete()

    for role_name, definition in ROLE_DEFINITIONS.items():
        group, _ = Group.objects.get_or_create(name=role_name)
        group.permissions.set(_permissions_for_role(definition))
