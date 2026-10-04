# projects/signals.py

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from common.models import Notification
from common.notifications import notify_user
from todos.models import TodoPriority
from todos.services import create_todo_once
from projects.utils import close_event_project_todos, request_project_for_event
from projects.models import (
    Project,
    Task,
    Deliverable,
    ProjectStatus,
    TaskStatus,
    DeliverableStatus,
)


@receiver(pre_save, sender=Project)
def cache_old_project_values(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return

    if not instance.pk:
        instance._old_manager_id = None
        instance._old_status = None
        return

    old = sender.objects.filter(pk=instance.pk).only("manager", "status").first()

    instance._old_manager_id = old.manager_id if old else None
    instance._old_status = old.status if old else None


@receiver(post_save, sender=Project)
def notify_and_todo_project_changes(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return

    old_manager_id = getattr(instance, "_old_manager_id", None)
    old_status = getattr(instance, "_old_status", None)
    actor = getattr(instance, "_notification_actor", None) or getattr(instance, "owner", None)

    if instance.manager_id and created:
        notify_user(
            recipient=instance.manager,
            actor=actor,
            notif_type=Notification.Type.PROJECT_ASSIGNED,
            target=instance,
            message=f"You have been assigned to project: {instance.name}",
            allow_duplicate=True,
        )

        create_todo_once(
            title=f"Review assigned project: {instance.name}",
            description=(
                "You have been assigned as the project manager. "
                "Please review the project details, dates, tasks and deliverables."
            ),
            owner=actor or instance.manager,
            assigned_to=instance.manager,
            priority=TodoPriority.HIGH,
            due_date=instance.start_date,
            project=instance,
            client=instance.client,
            deal=instance.deal,
        )

    elif instance.manager_id and old_manager_id != instance.manager_id:
        notify_user(
            recipient=instance.manager,
            actor=actor,
            notif_type=Notification.Type.PROJECT_ASSIGNED,
            target=instance,
            message=f"You have been assigned to project: {instance.name}",
            allow_duplicate=True,
        )

    elif instance.manager_id and not created:
        notify_user(
            recipient=instance.manager,
            actor=actor,
            notif_type=Notification.Type.PROJECT_ASSIGNED,
            target=instance,
            message=f"Project updated: {instance.name}",
            allow_duplicate=True,
        )

    if (
        not created
        and old_status != ProjectStatus.ACTIVE
        and instance.status == ProjectStatus.ACTIVE
    ):
        create_active_project_work_todos(instance, actor=actor)

    # Project completed -> CRM review pending
    if (
        not created
        and old_status != ProjectStatus.COMPLETED
        and instance.status == ProjectStatus.COMPLETED
    ):
        recipient = _resolve_project_review_recipient(instance)

        if recipient:
            notify_user(
                recipient=recipient,
                actor=instance.manager,
                notif_type=Notification.Type.PROJECT_COMPLETED_REVIEW_PENDING,
                target=instance,
                message=f"Project completed. Client review pending: {instance.name}",
            )

            create_todo_once(
                title=f"Collect client review: {instance.name}",
                description="Project is completed. Please contact the client and collect review/feedback.",
                owner=instance.manager or recipient,
                assigned_to=recipient,
                priority=TodoPriority.MEDIUM,
                due_date=None,
                project=instance,
                client=instance.client,
                deal=instance.deal,
            )


def _resolve_project_review_recipient(project):
    deal = getattr(project, "deal", None)
    client = getattr(project, "client", None)

    if deal:
        if getattr(deal, "owner_id", None):
            return deal.owner

        lead = getattr(deal, "lead", None)
        if lead and getattr(lead, "owner_id", None):
            return lead.owner

    if client and getattr(client, "owner_id", None):
        return client.owner

    return getattr(project, "manager", None)


def create_task_todo(task, actor=None):
    if not task.assigned_to_id:
        return None, False

    return create_todo_once(
        title=f"Complete assigned task: {task.name}",
        description=task.description or "Please complete this assigned task.",
        owner=actor or task.project.manager or task.assigned_to,
        assigned_to=task.assigned_to,
        priority=TodoPriority.HIGH,
        due_date=task.due_date,
        project=task.project,
        task=task,
    )


def create_deliverable_todo(deliverable, actor=None):
    if not deliverable.assigned_to_id:
        return None, False

    return create_todo_once(
        title=f"Complete assigned deliverable: {deliverable.name}",
        description=deliverable.description or "Please complete this assigned deliverable.",
        owner=actor or deliverable.project.manager or deliverable.assigned_to,
        assigned_to=deliverable.assigned_to,
        priority=TodoPriority.HIGH,
        due_date=deliverable.due_date,
        project=deliverable.project,
        deliverable=deliverable,
    )


def create_active_project_work_todos(project, actor=None):
    tasks = project.tasks.exclude(
        status__in=[TaskStatus.COMPLETED, TaskStatus.CANCELLED]
    ).select_related("assigned_to", "project__manager")

    for task in tasks:
        create_task_todo(task, actor=actor)

    deliverables = project.deliverables.exclude(
        status__in=[DeliverableStatus.DELIVERED, DeliverableStatus.CANCELLED]
    ).select_related("assigned_to", "project__manager")

    for deliverable in deliverables:
        create_deliverable_todo(deliverable, actor=actor)


@receiver(pre_save, sender=Task)
def cache_old_task_assignee(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return

    if not instance.pk:
        instance._old_assigned_to_id = None
        return

    old = sender.objects.filter(pk=instance.pk).only("assigned_to").first()
    instance._old_assigned_to_id = old.assigned_to_id if old else None


@receiver(post_save, sender=Task)
def notify_and_todo_task_assigned(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return

    if not instance.assigned_to_id:
        return

    old_assigned_to_id = getattr(instance, "_old_assigned_to_id", None)

    if not created and old_assigned_to_id == instance.assigned_to_id:
        return

    actor = (
        getattr(instance, "_notification_actor", None)
        or getattr(instance.project, "manager", None)
        or getattr(instance, "owner", None)
    )

    notify_user(
        recipient=instance.assigned_to,
        actor=actor,
        notif_type=Notification.Type.TASK_ASSIGNED,
        target=instance,
        message=f"You have been assigned a task: {instance.name}",
        allow_duplicate=True,
    )

    if instance.project.status == ProjectStatus.ACTIVE:
        create_task_todo(instance, actor=actor)


@receiver(pre_save, sender=Deliverable)
def cache_old_deliverable_assignee(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return

    if not instance.pk:
        instance._old_assigned_to_id = None
        return

    old = sender.objects.filter(pk=instance.pk).only("assigned_to").first()
    instance._old_assigned_to_id = old.assigned_to_id if old else None


@receiver(post_save, sender=Deliverable)
def notify_and_todo_deliverable_assigned(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return

    if not instance.assigned_to_id:
        return

    old_assigned_to_id = getattr(instance, "_old_assigned_to_id", None)

    if not created and old_assigned_to_id == instance.assigned_to_id:
        return

    actor = (
        getattr(instance, "_notification_actor", None)
        or getattr(instance.project, "manager", None)
        or getattr(instance, "owner", None)
    )

    notify_user(
        recipient=instance.assigned_to,
        actor=actor,
        notif_type=Notification.Type.DELIVERABLE_ASSIGNED,
        target=instance,
        message=f"You have been assigned a deliverable: {instance.name}",
        allow_duplicate=True,
    )

    if instance.project.status == ProjectStatus.ACTIVE:
        create_deliverable_todo(instance, actor=actor)


# ============================================================
# Event -> Project Manager hand-off
# ============================================================

@receiver(post_save, sender="events.Event")
def request_project_for_new_event(sender, instance, created, **kwargs):
    """
    New event without a project: every Project Manager is notified and gets
    a to-do. Once a project is linked, those to-dos are closed.
    """
    if kwargs.get("raw"):
        return

    if instance.project_id:
        close_event_project_todos(instance)
        return

    if created:
        actor = getattr(instance, "_notification_actor", None) or instance.owner
        transaction.on_commit(lambda: request_project_for_event(instance, actor=actor))


@receiver(post_save, sender=Project)
def close_event_todos_when_project_linked(sender, instance, created, **kwargs):
    if kwargs.get("raw") or not instance.event_id:
        return

    close_event_project_todos(instance.event)
