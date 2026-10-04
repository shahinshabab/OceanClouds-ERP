# todos/management/commands/generate_due_todos.py

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from common.roles import ROLE_ADMIN
from todos.models import TodoPriority
from todos.services import create_todo_once


User = get_user_model()


class Command(BaseCommand):
    help = "Auto-generate daily todos for CRM, Sales, Project, Task, Deliverable, Invoice and Event due items."

    def handle(self, *args, **options):
        self.today = timezone.localdate()
        self.created_count = 0

        self.generate_lead_next_action_todos()
        self.generate_deal_followup_todos()
        self.generate_proposal_validity_todos()
        self.generate_contract_start_todos()
        self.generate_contract_end_todos()
        self.generate_invoice_due_todos()

        self.generate_admin_project_due_todos()
        self.generate_project_review_collection_todos()
        self.generate_project_close_todos()

        self.generate_task_due_todos()
        self.generate_deliverable_due_todos()
        self.generate_event_checklist_todos()

        self.stdout.write(
            self.style.SUCCESS(
                f"Daily due todo generation completed. Created {self.created_count} new todos."
            )
        )

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    def add_count(self, created):
        if created:
            self.created_count += 1

    def get_admin_users(self):
        return (
            User.objects
            .filter(
                is_active=True,
                groups__name=ROLE_ADMIN,
            )
            .distinct()
        )

    # ------------------------------------------------------------
    # CRM: Lead next action date
    # ------------------------------------------------------------

    def generate_lead_next_action_todos(self):
        from crm.models import Lead

        leads = (
            Lead.objects
            .select_related("owner", "client")
            .filter(next_action_date=self.today)
            .exclude(status__in=[
                Lead.STATUS_LOST,
                Lead.STATUS_CONVERTED_TO_DEAL,
            ])
        )

        for lead in leads:
            assigned_user = lead.owner

            if not assigned_user:
                continue

            note = lead.next_action_note or "Please follow up this lead."

            _, created = create_todo_once(
                title=f"Lead next action: {lead.name}",
                description=note,
                owner=assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.HIGH,
                due_date=self.today,
                client=lead.client,
                lead=lead,
            )

            self.add_count(created)

    # ------------------------------------------------------------
    # Sales: Deal expected close date
    # ------------------------------------------------------------

    def generate_deal_followup_todos(self):
        from sales.models import Deal, DealStage

        deals = (
            Deal.objects
            .select_related("owner", "client", "lead")
            .filter(expected_close_date=self.today)
            .exclude(stage__in=[
                DealStage.WON,
                DealStage.LOST,
            ])
        )

        for deal in deals:
            assigned_user = deal.owner

            if not assigned_user and deal.lead_id:
                assigned_user = deal.lead.owner

            if not assigned_user:
                continue

            _, created = create_todo_once(
                title=f"Deal follow-up: {deal.name}",
                description=(
                    "Today is the expected closing date for this deal. "
                    "Please follow up with the client."
                ),
                owner=assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.HIGH,
                due_date=self.today,
                client=deal.client,
                lead=deal.lead,
                deal=deal,
            )

            self.add_count(created)

    # ------------------------------------------------------------
    # Sales: Proposal valid until date
    # ------------------------------------------------------------

    def generate_proposal_validity_todos(self):
        from sales.models import Proposal, ProposalStatus

        proposals = (
            Proposal.objects
            .select_related("owner", "deal", "deal__client", "deal__lead")
            .filter(valid_until=self.today)
            .exclude(status__in=[
                ProposalStatus.ACCEPTED,
                ProposalStatus.REJECTED,
                ProposalStatus.EXPIRED,
            ])
        )

        for proposal in proposals:
            deal = proposal.deal
            assigned_user = proposal.owner or deal.owner

            if not assigned_user and deal.lead_id:
                assigned_user = deal.lead.owner

            if not assigned_user:
                continue

            _, created = create_todo_once(
                title=f"Proposal validity ends today: {proposal}",
                description=(
                    "This proposal validity ends today. "
                    "Please follow up with the client or update the proposal status."
                ),
                owner=assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.HIGH,
                due_date=self.today,
                client=deal.client,
                lead=deal.lead,
                deal=deal,
                proposal=proposal,
            )

            self.add_count(created)

    # ------------------------------------------------------------
    # Sales: Contract start date
    # ------------------------------------------------------------

    def generate_contract_start_todos(self):
        from sales.models import Contract, ContractStatus

        contracts = (
            Contract.objects
            .select_related("owner", "deal", "deal__client", "deal__lead", "proposal")
            .filter(start_date=self.today)
            .exclude(status=ContractStatus.CANCELLED)
        )

        for contract in contracts:
            deal = contract.deal
            assigned_user = contract.owner or deal.owner

            if not assigned_user and deal.lead_id:
                assigned_user = deal.lead.owner

            if not assigned_user:
                continue

            _, created = create_todo_once(
                title=f"Contract starts today: {contract}",
                description=(
                    "This contract starts today. "
                    "Please review the contract and make sure the required work is ready."
                ),
                owner=assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.MEDIUM,
                due_date=self.today,
                client=deal.client,
                lead=deal.lead,
                deal=deal,
                proposal=contract.proposal,
                contract=contract,
            )

            self.add_count(created)

    # ------------------------------------------------------------
    # Sales: Contract end date
    # ------------------------------------------------------------

    def generate_contract_end_todos(self):
        from sales.models import Contract, ContractStatus

        contracts = (
            Contract.objects
            .select_related("owner", "deal", "deal__client", "deal__lead", "proposal")
            .filter(end_date=self.today)
            .exclude(status=ContractStatus.CANCELLED)
        )

        for contract in contracts:
            deal = contract.deal
            assigned_user = contract.owner or deal.owner

            if not assigned_user and deal.lead_id:
                assigned_user = deal.lead.owner

            if not assigned_user:
                continue

            _, created = create_todo_once(
                title=f"Contract ends today: {contract}",
                description=(
                    "This contract ends today. "
                    "Please check completion, pending payments, and client follow-up."
                ),
                owner=assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.HIGH,
                due_date=self.today,
                client=deal.client,
                lead=deal.lead,
                deal=deal,
                proposal=contract.proposal,
                contract=contract,
            )

            self.add_count(created)

    # ------------------------------------------------------------
    # Sales: Invoice due date
    # ------------------------------------------------------------

    def generate_invoice_due_todos(self):
        from sales.models import Invoice, InvoiceStatus

        invoices = (
            Invoice.objects
            .select_related("owner", "deal", "deal__client", "deal__lead", "contract")
            .filter(due_date=self.today)
            .exclude(status__in=[
                InvoiceStatus.PAID,
                InvoiceStatus.CANCELLED,
            ])
        )

        for invoice in invoices:
            deal = invoice.deal
            assigned_user = invoice.owner or deal.owner

            if not assigned_user and deal.lead_id:
                assigned_user = deal.lead.owner

            if not assigned_user:
                continue

            _, created = create_todo_once(
                title=f"Invoice due today: {invoice}",
                description="Invoice is due today. Please follow up payment with the client.",
                owner=assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.URGENT,
                due_date=self.today,
                client=deal.client,
                lead=deal.lead,
                deal=deal,
                contract=invoice.contract,
                invoice=invoice,
            )

            self.add_count(created)

    # ------------------------------------------------------------
    # Admin: Project due date
    # ------------------------------------------------------------

    def generate_admin_project_due_todos(self):
        from projects.models import Project, ProjectStatus

        projects = (
            Project.objects
            .select_related("owner", "manager", "client", "deal")
            .filter(due_date=self.today)
            .exclude(status__in=[
                ProjectStatus.COMPLETED,
                ProjectStatus.CLOSED,
                ProjectStatus.CANCELLED,
            ])
        )

        admins = list(self.get_admin_users())

        for project in projects:
            for admin in admins:
                _, created = create_todo_once(
                    title=f"Project due today: {project.name}",
                    description=(
                        "This project is due today. "
                        "Please check the project status, pending tasks and deliverables."
                    ),
                    owner=admin,
                    assigned_to=admin,
                    priority=TodoPriority.URGENT,
                    due_date=self.today,
                    project=project,
                    client=project.client,
                    deal=project.deal,
                )

                self.add_count(created)
    # ------------------------------------------------------------
    # Project manager/Admin: Collect client review after project completion
    # ------------------------------------------------------------

    def generate_project_review_collection_todos(self):
        from projects.models import Project, ProjectStatus

        projects = (
            Project.objects
            .select_related("owner", "manager", "client", "deal")
            .filter(
                status=ProjectStatus.COMPLETED,
                client__isnull=False,
            )
            .exclude(client__reviews__isnull=False)
            .distinct()
        )

        admins = list(self.get_admin_users())

        for project in projects:
            assigned_user = project.manager or project.owner

            users_to_notify = []
            if assigned_user:
                users_to_notify.append(assigned_user)
            else:
                users_to_notify.extend(admins)

            for user in users_to_notify:
                _, created = create_todo_once(
                    title=f"Collect client review: {project.name}",
                    description=(
                        "This project is completed, but the client review has not been collected yet. "
                        "Please collect and save the client review before closing the project."
                    ),
                    owner=user,
                    assigned_to=user,
                    priority=TodoPriority.HIGH,
                    due_date=self.today,
                    project=project,
                    client=project.client,
                    deal=project.deal,
                )

                self.add_count(created)

    # ------------------------------------------------------------
    # Project manager/Admin: Close project after review is collected
    # ------------------------------------------------------------

    def generate_project_close_todos(self):
        from projects.models import Project, ProjectStatus

        projects = (
            Project.objects
            .select_related("owner", "manager", "client", "deal")
            .filter(
                status=ProjectStatus.COMPLETED,
                client__isnull=False,
                client__reviews__isnull=False,
            )
            .distinct()
        )

        admins = list(self.get_admin_users())

        for project in projects:
            assigned_user = project.manager or project.owner

            users_to_notify = []
            if assigned_user:
                users_to_notify.append(assigned_user)
            else:
                users_to_notify.extend(admins)

            for user in users_to_notify:
                _, created = create_todo_once(
                    title=f"Close completed project: {project.name}",
                    description=(
                        "The project is completed and client review is collected. "
                        "Please verify final payment/status and close the project."
                    ),
                    owner=user,
                    assigned_to=user,
                    priority=TodoPriority.MEDIUM,
                    due_date=self.today,
                    project=project,
                    client=project.client,
                    deal=project.deal,
                )

                self.add_count(created)
    # ------------------------------------------------------------
    # Employee: Task due date
    # ------------------------------------------------------------

    def generate_task_due_todos(self):
        from projects.models import Task, TaskStatus

        tasks = (
            Task.objects
            .select_related("owner", "assigned_to", "project", "project__manager")
            .filter(due_date=self.today)
            .exclude(status__in=[
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
            ])
        )

        for task in tasks:
            assigned_user = task.assigned_to

            if not assigned_user:
                continue

            _, created = create_todo_once(
                title=f"Task due today: {task.name}",
                description="This task is due today. Please complete it or update the task status.",
                owner=task.project.manager or task.owner or assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.URGENT,
                due_date=self.today,
                project=task.project,
                task=task,
            )

            self.add_count(created)

    # ------------------------------------------------------------
    # Employee: Deliverable due date
    # ------------------------------------------------------------

    def generate_deliverable_due_todos(self):
        from projects.models import Deliverable, DeliverableStatus

        deliverables = (
            Deliverable.objects
            .select_related("owner", "assigned_to", "project", "project__manager")
            .filter(due_date=self.today)
            .exclude(status__in=[
                DeliverableStatus.DELIVERED,
                DeliverableStatus.CANCELLED,
            ])
        )

        for deliverable in deliverables:
            assigned_user = deliverable.assigned_to

            if not assigned_user:
                continue

            _, created = create_todo_once(
                title=f"Deliverable due today: {deliverable.name}",
                description="This deliverable is due today. Please complete it or update its status.",
                owner=deliverable.project.manager or deliverable.owner or assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.URGENT,
                due_date=self.today,
                project=deliverable.project,
                deliverable=deliverable,
            )

            self.add_count(created)

    # ------------------------------------------------------------
    # Project manager: Event checklist todos
    # ------------------------------------------------------------

    def generate_event_checklist_todos(self):
        from events.models import Event, EventStatus

        events = (
            Event.objects
            .select_related("owner", "project", "project__manager", "client")
            .filter(date=self.today)
            .exclude(status__in=[
                EventStatus.COMPLETED,
                EventStatus.CANCELLED,
            ])
        )

        for event in events:
            assigned_user = None

            if event.project_id and event.project.manager_id:
                assigned_user = event.project.manager
            else:
                assigned_user = event.owner

            if not assigned_user:
                continue

            pending_items = event.checklist.items.filter(is_done=False)

            if not pending_items.exists():
                continue

            _, created = create_todo_once(
                title=f"Check event checklist: {event.name}",
                description=(
                    f"Event is scheduled today. "
                    f"There are {pending_items.count()} pending checklist item(s). "
                    "Please review and complete the checklist."
                ),
                owner=event.owner or assigned_user,
                assigned_to=assigned_user,
                priority=TodoPriority.URGENT,
                due_date=self.today,
                project=event.project,
                client=event.client,
                event=event,
            )

            self.add_count(created)

            for item in pending_items:
                item_assigned_user = item.assigned_to or assigned_user

                _, created = create_todo_once(
                    title=f"Event checklist item due: {item.title}",
                    description=item.notes or "Please complete this event checklist item.",
                    owner=item.owner or event.owner or assigned_user,
                    assigned_to=item_assigned_user,
                    priority=TodoPriority.HIGH,
                    due_date=self.today,
                    project=event.project,
                    client=event.client,
                    event=event,
                    checklist_item=item,
                )

                self.add_count(created)