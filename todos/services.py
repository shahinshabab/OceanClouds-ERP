# todos/services.py

from django.db.models import Q

from todos.models import Todo, TodoStatus, TodoPriority


def create_todo_once(
    *,
    title,
    owner,
    assigned_to=None,
    description="",
    priority=TodoPriority.MEDIUM,
    due_date=None,
    project=None,
    task=None,
    deliverable=None,
    client=None,
    lead=None,
    deal=None,
    proposal=None,
    contract=None,
    invoice=None,
    event=None,
    checklist_item=None,
    done_since=None,
):
    """
    Create a to-do only if a similar open to-do does not already exist.

    This prevents duplicate auto-generated todos from cron or signals.
    With done_since (a date), a matching to-do created on or after that date
    also counts even if it is already done, so a job that runs more than once
    a day does not bring back a to-do someone just finished.
    """

    if not owner:
        owner = assigned_to

    if not assigned_to:
        assigned_to = owner

    if not owner or not assigned_to:
        return None, False

    open_or_recent = Q(status__in=[TodoStatus.PENDING, TodoStatus.IN_PROGRESS])
    if done_since:
        open_or_recent |= Q(created_at__date__gte=done_since)

    duplicate_qs = Todo.objects.filter(
        open_or_recent,
        title=title,
        assigned_to=assigned_to,
    )

    if project:
        duplicate_qs = duplicate_qs.filter(project=project)

    if task:
        duplicate_qs = duplicate_qs.filter(task=task)

    if deliverable:
        duplicate_qs = duplicate_qs.filter(deliverable=deliverable)

    if client:
        duplicate_qs = duplicate_qs.filter(client=client)

    if lead:
        duplicate_qs = duplicate_qs.filter(lead=lead)

    if deal:
        duplicate_qs = duplicate_qs.filter(deal=deal)

    if proposal:
        duplicate_qs = duplicate_qs.filter(proposal=proposal)

    if contract:
        duplicate_qs = duplicate_qs.filter(contract=contract)

    if invoice:
        duplicate_qs = duplicate_qs.filter(invoice=invoice)

    if event:
        duplicate_qs = duplicate_qs.filter(event=event)

    if checklist_item:
        duplicate_qs = duplicate_qs.filter(checklist_item=checklist_item)

    existing = duplicate_qs.first()

    if existing:
        return existing, False

    todo = Todo.objects.create(
        title=title,
        description=description,
        owner=owner,
        assigned_to=assigned_to,
        status=TodoStatus.PENDING,
        priority=priority,
        due_date=due_date,
        project=project,
        task=task,
        deliverable=deliverable,
        client=client,
        lead=lead,
        deal=deal,
        proposal=proposal,
        contract=contract,
        invoice=invoice,
        event=event,
        checklist_item=checklist_item,
    )

    return todo, True