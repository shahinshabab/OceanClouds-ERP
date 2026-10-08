from common.roles import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER, user_has_role

from .models import (
    Deliverable,
    DeliverableStatus,
    Project,
    Task,
    TaskStatus,
    WorkSession,
    WorkSessionStatus,
)


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
    ).prefetch_related(
        "tasks",
        "deliverables",
        "events",
    )

    # Project Managers have full project access, not only their own projects.
    if is_admin_or_project_manager(user):
        return qs

    return Project.objects.none()


def visible_tasks_for(user):
    qs = Task.objects.select_related(
        "project",
        "project__client",
        "project__manager",
        "assigned_to",
    )

    if is_admin_or_project_manager(user):
        return qs

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

    if is_admin_or_project_manager(user):
        return qs

    if is_employee(user):
        return qs.filter(assigned_to=user)

    return Deliverable.objects.none()


def can_manage_project_work(user):
    """
    Create/edit projects, tasks and deliverables: Admin and Project Manager.
    """
    return is_admin_or_project_manager(user)


def can_self_assign(user, obj):
    """
    Staff who manage project work can take a task or deliverable themselves.
    """
    if not user.is_authenticated or not can_manage_project_work(user):
        return False
    return obj.assigned_to_id != user.id


def user_has_active_work(user):
    return WorkSession.objects.filter(
        user=user,
        status=WorkSessionStatus.ACTIVE,
    ).exists()


def pause_active_work_sessions_for_user(user, paused_at=None):
    user_filter = {"user_id": user} if isinstance(user, int) else {"user": user}
    sessions = (
        WorkSession.objects
        .filter(
            status=WorkSessionStatus.ACTIVE,
            **user_filter,
        )
        .select_related("task", "deliverable")
    )

    for session in sessions:
        session.pause(paused_at=paused_at)

        if session.task_id:
            session.task.status = TaskStatus.PAUSED
            session.task.save(update_fields=["status"])
            continue

        if session.deliverable_id:
            session.deliverable.status = DeliverableStatus.PAUSED
            session.deliverable.save(update_fields=["status"])


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


# ============================================================
# Event -> project hand-off
# ============================================================

EVENT_PROJECT_TODO_PREFIX = "Create project for event: "


def project_managers():
    from django.contrib.auth import get_user_model

    return (
        get_user_model().objects.filter(is_active=True, groups__name=ROLE_PROJECT_MANAGER)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )


def event_needs_project(event):
    return not event.project_id


def contract_sibling_events(event):
    """
    Other events created from the same contract (reception, wedding day, ...)
    that are not in a project yet. They belong in the same project.
    """
    from events.models import Event

    if not event.contract_id:
        return Event.objects.none()
    return (
        Event.objects.filter(contract_id=event.contract_id, project__isnull=True)
        .exclude(pk=event.pk)
        .order_by("date", "start_time", "name")
    )


def request_project_for_event(event, actor=None):
    """
    A new event has no project yet: tell every Project Manager and give each
    of them a to-do to plan the project from the event and its contract.
    """
    from common.models import Notification
    from common.notifications import notify_user
    from todos.models import TodoPriority
    from todos.services import create_todo_once

    if not event_needs_project(event):
        return []

    # A contract creates one event per day; one project covers them all, so
    # only the first of them asks for it.
    if contract_sibling_events(event).filter(pk__lt=event.pk).exists():
        return []

    created = []
    when = event.date.strftime("%d %b %Y") if event.date else "date not set"
    description = (
        f"{event.name} on {when} has no project yet. "
        "Open the event, check the client and the contract, then create the project "
        "and schedule its tasks and deliverables."
    )
    siblings = list(contract_sibling_events(event))
    if siblings:
        description += " The same project covers the contract's other events: " + ", ".join(
            sibling.name for sibling in siblings
        ) + "."

    for manager in project_managers():
        notify_user(
            recipient=manager,
            actor=actor,
            notif_type=Notification.Type.EVENT_NEEDS_PROJECT,
            target=event,
            message=f"New event needs a project: {event.name} ({when})",
        )
        todo, was_created = create_todo_once(
            title=f"{EVENT_PROJECT_TODO_PREFIX}{event.name}",
            description=description,
            owner=actor or event.owner or manager,
            assigned_to=manager,
            priority=TodoPriority.HIGH,
            due_date=event.date,
            event=event,
            client=event.client,
            contract=event.contract,
        )
        if was_created:
            created.append(todo)

    return created


def close_event_project_todos(event):
    """
    The event now has a project: the open "create project" to-dos are done.
    """
    from todos.models import Todo, TodoStatus

    todos = Todo.objects.filter(
        event=event,
        title__startswith=EVENT_PROJECT_TODO_PREFIX,
        status__in=[TodoStatus.PENDING, TodoStatus.IN_PROGRESS],
    )
    for todo in todos:
        todo.mark_completed()
