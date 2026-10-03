from common.roles import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER, user_has_role

from .models import Deliverable, Project, Task, WorkSession, WorkSessionStatus


def _scope_tags(*scopes):
    """
    Usage:
        _scope_tags("project")
        returns: "scope:project"

        _scope_tags("project", "email")
        returns: "scope:project scope:email"
    """

    tags = []

    for scope in scopes:
        if not scope:
            continue

        scope = str(scope).strip()

        if not scope:
            continue

        if scope.startswith("scope:"):
            tags.append(scope)
        else:
            tags.append(f"scope:{scope}")

    return " ".join(tags)


def _validation_error_message(exc):
    """
    Converts Django ValidationError to a clean readable message.
    """

    if hasattr(exc, "message_dict"):
        return " ".join(
            msg
            for messages_list in exc.message_dict.values()
            for msg in messages_list
        )

    if hasattr(exc, "messages"):
        return " ".join(exc.messages)

    return str(exc)


def _form_error_message(form, default_message):
    """
    Converts form errors to a clean single message.
    """

    if not form.errors:
        return default_message

    all_errors = []

    for field, errors in form.errors.items():
        label = field

        if field != "__all__" and field in form.fields:
            label = form.fields[field].label or field

        for error in errors:
            if field == "__all__":
                all_errors.append(str(error))
            else:
                all_errors.append(f"{label}: {error}")

    if all_errors:
        return " ".join(all_errors)

    return default_message


# ============================================================
# Role helpers
# ============================================================

def is_admin(user):
    return user_has_role(user, ROLE_ADMIN)


def is_project_manager(user):
    return user_has_role(user, ROLE_PROJECT_MANAGER)


def is_employee(user):
    return user_has_role(user, ROLE_EMPLOYEE)


def is_admin_or_project_manager(user):
    return is_admin(user) or is_project_manager(user)


def visible_projects_for(user):
    qs = Project.objects.select_related(
        "client",
        "deal",
        "manager",
        "event",
    ).prefetch_related(
        "tasks",
        "deliverables",
    )

    if is_admin(user):
        return qs

    if is_project_manager(user):
        return qs.filter(manager=user)

    return Project.objects.none()


def visible_tasks_for(user):
    qs = Task.objects.select_related(
        "project",
        "project__client",
        "project__manager",
        "assigned_to",
    )

    if is_admin(user):
        return qs

    if is_project_manager(user):
        return qs.filter(project__manager=user)

    if is_employee(user):
        return qs.filter(assigned_to=user)

    return Task.objects.none()


def visible_deliverables_for(user):
    qs = Deliverable.objects.select_related(
        "project",
        "project__client",
        "project__manager",
        "assigned_to",
    ).prefetch_related("tasks")

    if is_admin(user):
        return qs

    if is_project_manager(user):
        return qs.filter(project__manager=user)

    if is_employee(user):
        return qs.filter(assigned_to=user)

    return Deliverable.objects.none()


def user_has_active_work(user):
    return WorkSession.objects.filter(
        user=user,
        status=WorkSessionStatus.ACTIVE,
    ).exists()


def close_active_work_for_target(user, task=None, deliverable=None):
    qs = WorkSession.objects.filter(
        user=user,
        status__in=[
            WorkSessionStatus.ACTIVE,
            WorkSessionStatus.PAUSED,
        ],
    )

    if task:
        qs = qs.filter(task=task)

    if deliverable:
        qs = qs.filter(deliverable=deliverable)

    for session in qs:
        session.end()
