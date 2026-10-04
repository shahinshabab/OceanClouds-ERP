from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from common.models import Notification
from common.test_helpers import AuthenticatedViewTestMixin, make_user
from crm.models import Client, Review
from todos.models import Todo

from .models import (
    Deliverable,
    DeliverableStatus,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    WorkSession,
    WorkSessionStatus,
)
from .utils import pause_active_work_sessions_for_user


class ProjectsTests(AuthenticatedViewTestMixin):
    list_url_names = [
        "projects:project_list",
        "projects:project_kanban",
        "projects:task_list",
        "projects:task_kanban",
        "projects:deliverable_list",
        "projects:deliverable_kanban",
    ]

    def test_standard_pages_use_shared_ui_and_kanban_opts_out(self):
        self.client.force_login(self.user)

        standard_response = self.client.get(reverse("projects:project_list"))
        kanban_response = self.client.get(reverse("projects:project_kanban"))

        standard_html = standard_response.content.decode()
        kanban_html = kanban_response.content.decode()

        self.assertIn('class="app-shell standard-page"', standard_html)
        self.assertIn('class="app-shell kanban-page"', kanban_html)
        self.assertNotIn('class="app-shell standard-page"', kanban_html)

    def test_project_progress_and_completion_flow(self):
        project = Project.objects.create(name="Production")
        task = Task.objects.create(project=project, name="Edit", status=TaskStatus.COMPLETED)
        deliverable = Deliverable.objects.create(
            project=project,
            name="Film",
            status=DeliverableStatus.DELIVERED,
        )
        deliverable.tasks.add(task)

        self.assertEqual(project.progress_percent, 100)
        self.assertTrue(project.can_be_completed)

        project.mark_completed()
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.COMPLETED)
        self.assertIsNotNone(project.completed_at)

    def test_project_cannot_close_with_client_until_review_exists(self):
        client = Client.objects.create(name="Review Client")
        project = Project.objects.create(name="Close Test", client=client)

        with self.assertRaises(ValidationError):
            project.mark_closed()

        task = Task.objects.create(project=project, name="Edit", status=TaskStatus.COMPLETED)
        deliverable = Deliverable.objects.create(
            project=project,
            name="Film",
            status=DeliverableStatus.DELIVERED,
        )
        deliverable.tasks.add(task)
        project.mark_completed()

        with self.assertRaises(ValidationError):
            project.mark_closed()

        Review.objects.create(client=client, title="Good")
        project.mark_closed()
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.CLOSED)

    def test_task_and_deliverable_overdue_properties(self):
        project = Project.objects.create(name="Overdue")
        yesterday = timezone.localdate() - timedelta(days=1)
        task = Task.objects.create(project=project, name="Task", due_date=yesterday)
        deliverable = Deliverable.objects.create(
            project=project,
            name="Deliverable",
            due_date=yesterday,
        )

        self.assertTrue(task.is_overdue)
        self.assertTrue(deliverable.is_overdue)

    def test_deliverable_requires_linked_tasks_completed_before_delivery(self):
        project = Project.objects.create(name="Delivery")
        task = Task.objects.create(project=project, name="Edit")
        deliverable = Deliverable.objects.create(project=project, name="Film")
        deliverable.tasks.add(task)

        with self.assertRaises(ValidationError):
            deliverable.mark_delivered()

        task.mark_completed()
        deliverable.mark_delivered()
        deliverable.refresh_from_db()
        self.assertEqual(deliverable.status, DeliverableStatus.DELIVERED)

    def test_work_session_pause_resume_end(self):
        user = make_user(username="worker")
        project = Project.objects.create(name="Timer")
        task = Task.objects.create(project=project, name="Edit")
        session = WorkSession.objects.create(user=user, project=project, task=task)

        self.assertEqual(session.status, WorkSessionStatus.ACTIVE)
        session.pause()
        session.refresh_from_db()
        self.assertEqual(session.status, WorkSessionStatus.PAUSED)

        session.resume()
        session.refresh_from_db()
        self.assertEqual(session.status, WorkSessionStatus.ACTIVE)

        session.end()
        session.refresh_from_db()
        self.assertEqual(session.status, WorkSessionStatus.ENDED)

    def test_pause_clears_resume_marker_and_freezes_work_time(self):
        user = make_user(username="pause-freeze-worker")
        project = Project.objects.create(name="Freeze Timer")
        task = Task.objects.create(project=project, name="Edit")
        session = WorkSession.objects.create(
            user=user,
            project=project,
            task=task,
            last_resumed_at=timezone.now() - timedelta(hours=2),
        )

        session.pause()
        session.refresh_from_db()

        self.assertEqual(session.status, WorkSessionStatus.PAUSED)
        self.assertIsNone(session.last_resumed_at)
        self.assertGreaterEqual(session.work_seconds, 7200)
        self.assertEqual(session.live_work_seconds, session.work_seconds)

    def test_pause_active_work_sessions_for_user_pauses_task_status(self):
        user = make_user(username="logout-pause-worker")
        project = Project.objects.create(name="Logout Timer")
        task = Task.objects.create(
            project=project,
            name="Edit",
            status=TaskStatus.IN_PROGRESS,
        )
        session = WorkSession.objects.create(user=user, project=project, task=task)

        pause_active_work_sessions_for_user(user)

        session.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(session.status, WorkSessionStatus.PAUSED)
        self.assertEqual(task.status, TaskStatus.PAUSED)

    def test_pause_active_work_sessions_for_user_pauses_deliverable_status(self):
        user = make_user(username="logout-pause-deliverable-worker")
        project = Project.objects.create(name="Logout Deliverable Timer")
        deliverable = Deliverable.objects.create(
            project=project,
            name="Film",
            status=DeliverableStatus.IN_PROGRESS,
        )
        session = WorkSession.objects.create(
            user=user,
            project=project,
            deliverable=deliverable,
        )

        paused_at = timezone.now()
        pause_active_work_sessions_for_user(user.id, paused_at=paused_at)

        session.refresh_from_db()
        deliverable.refresh_from_db()
        self.assertEqual(session.status, WorkSessionStatus.PAUSED)
        self.assertEqual(session.paused_at, paused_at)
        self.assertEqual(deliverable.status, DeliverableStatus.PAUSED)

    def test_project_manager_is_notified_when_project_assignment_changes(self):
        actor = make_user(username="project-actor")
        manager = make_user(username="project-manager")
        project = Project.objects.create(name="Assignment")

        project.manager = manager
        project._notification_actor = actor
        project.save()

        notification = Notification.objects.get(
            recipient=manager,
            notif_type=Notification.Type.PROJECT_ASSIGNED,
            object_id=project.pk,
        )
        self.assertEqual(notification.actor, actor)
        self.assertIn(project.name, notification.message)

    def test_project_manager_gets_todo_when_project_is_created(self):
        manager = make_user(username="project-create-manager")

        project = Project.objects.create(name="New Project", manager=manager)

        todo = Todo.objects.get(
            assigned_to=manager,
            project=project,
            title=f"Review assigned project: {project.name}",
        )
        self.assertEqual(todo.owner, manager)

    def test_project_manager_is_notified_when_existing_project_is_updated(self):
        actor = make_user(username="project-update-actor")
        manager = make_user(username="project-update-manager")
        project = Project.objects.create(name="Before", manager=manager)
        Notification.objects.all().delete()

        project.name = "After"
        project._notification_actor = actor
        project.save()

        notification = Notification.objects.get(
            recipient=manager,
            notif_type=Notification.Type.PROJECT_ASSIGNED,
            object_id=project.pk,
        )
        self.assertEqual(notification.actor, actor)
        self.assertEqual(notification.message, "Project updated: After")

    def test_task_assignee_is_notified_each_time_assignment_changes_to_them(self):
        actor = make_user(username="task-actor")
        assignee = make_user(username="task-assignee")
        other_assignee = make_user(username="task-other-assignee")
        project = Project.objects.create(name="Task Assignment")
        task = Task.objects.create(project=project, name="Editing")

        task.assigned_to = assignee
        task._notification_actor = actor
        task.save()

        task.assigned_to = other_assignee
        task._notification_actor = actor
        task.save()

        task.assigned_to = assignee
        task._notification_actor = actor
        task.save()

        self.assertEqual(
            Notification.objects.filter(
                recipient=assignee,
                notif_type=Notification.Type.TASK_ASSIGNED,
                object_id=task.pk,
            ).count(),
            2,
        )

    def test_task_todo_waits_until_project_becomes_active(self):
        actor = make_user(username="task-active-actor")
        assignee = make_user(username="task-active-assignee")
        project = Project.objects.create(name="Planned Project")
        task = Task.objects.create(project=project, name="Editing")

        task.assigned_to = assignee
        task._notification_actor = actor
        task.save()

        self.assertTrue(
            Notification.objects.filter(
                recipient=assignee,
                notif_type=Notification.Type.TASK_ASSIGNED,
                object_id=task.pk,
            ).exists()
        )
        self.assertFalse(Todo.objects.filter(assigned_to=assignee, task=task).exists())

        project.status = ProjectStatus.ACTIVE
        project._notification_actor = actor
        project.save()

        self.assertTrue(Todo.objects.filter(assigned_to=assignee, task=task).exists())

    def test_deliverable_assignee_is_notified_when_assignment_changes(self):
        actor = make_user(username="deliverable-actor")
        assignee = make_user(username="deliverable-assignee")
        project = Project.objects.create(name="Deliverable Assignment")
        deliverable = Deliverable.objects.create(project=project, name="Album")

        deliverable.assigned_to = assignee
        deliverable._notification_actor = actor
        deliverable.save()

        notification = Notification.objects.get(
            recipient=assignee,
            notif_type=Notification.Type.DELIVERABLE_ASSIGNED,
            object_id=deliverable.pk,
        )
        self.assertEqual(notification.actor, actor)
        self.assertIn(deliverable.name, notification.message)

    def test_deliverable_todo_is_created_immediately_for_active_project(self):
        actor = make_user(username="deliverable-active-actor")
        assignee = make_user(username="deliverable-active-assignee")
        project = Project.objects.create(
            name="Active Deliverable Project",
            status=ProjectStatus.ACTIVE,
        )
        deliverable = Deliverable.objects.create(project=project, name="Album")

        deliverable.assigned_to = assignee
        deliverable._notification_actor = actor
        deliverable.save()

        self.assertTrue(
            Todo.objects.filter(
                assigned_to=assignee,
                deliverable=deliverable,
                title=f"Complete assigned deliverable: {deliverable.name}",
            ).exists()
        )

    def test_work_duration_hm_uses_sixty_minutes_per_hour(self):
        user = make_user(username="duration-worker")
        project = Project.objects.create(name="Duration Project")
        task = Task.objects.create(project=project, name="Duration Task")
        deliverable = Deliverable.objects.create(project=project, name="Duration Deliverable")

        task_session = WorkSession.objects.create(
            user=user,
            project=project,
            task=task,
            status=WorkSessionStatus.PAUSED,
            work_seconds=100 * 60,
        )
        WorkSession.objects.create(
            user=user,
            project=project,
            deliverable=deliverable,
            status=WorkSessionStatus.PAUSED,
            work_seconds=100 * 60,
        )

        self.assertEqual(task_session.live_work_hm, "1h 40m")
        self.assertEqual(task.total_work_hm, "1h 40m")
        self.assertEqual(deliverable.total_work_hm, "1h 40m")
        self.assertEqual(project.total_work_hm, "3h 20m")



def make_role_user(username, role):
    from django.contrib.auth.models import Group

    user = make_user(username=username, is_staff=False)
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


class ProjectManagerAccessTests(TestCase):
    """
    Project Managers run projects end to end: create, edit, self-assign,
    and get a to-do when an event has no project yet.
    """

    @classmethod
    def setUpTestData(cls):
        from common.roles import ROLE_CRM_MANAGER, ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER

        cls.pm = make_role_user("pm-one", ROLE_PROJECT_MANAGER)
        cls.other_pm = make_role_user("pm-two", ROLE_PROJECT_MANAGER)
        cls.crm = make_role_user("crm-one", ROLE_CRM_MANAGER)
        cls.employee = make_role_user("emp-one", ROLE_EMPLOYEE)

    def test_pm_can_create_project_and_becomes_manager(self):
        self.client.force_login(self.pm)
        response = self.client.get(reverse("projects:project_create"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("projects:project_create"),
            {"name": "PM Project", "status": ProjectStatus.PLANNED, "priority": "medium"},
        )
        project = Project.objects.get(name="PM Project")
        self.assertRedirects(response, reverse("projects:project_detail", args=[project.pk]))
        self.assertEqual(project.manager, self.pm)

    def test_pm_sees_and_edits_projects_managed_by_others(self):
        project = Project.objects.create(name="Someone Else", manager=self.other_pm)
        self.client.force_login(self.pm)

        self.assertEqual(
            self.client.get(reverse("projects:project_detail", args=[project.pk])).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("projects:project_update", args=[project.pk])).status_code, 200
        )

    def test_employee_cannot_create_project(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("projects:project_create")).status_code, 403)

    def test_pm_is_offered_as_assignee_and_can_self_assign(self):
        project = Project.objects.create(name="Self Managed", manager=self.pm)
        task = Task.objects.create(project=project, name="Colour grade")
        deliverable = Deliverable.objects.create(project=project, name="Teaser")

        from .forms import DeliverableForm, TaskForm

        form = TaskForm(user=self.pm, project=project)
        self.assertIn(self.pm, form.fields["assigned_to"].queryset)
        self.assertIn(self.employee, form.fields["assigned_to"].queryset)
        self.assertIn("(me)", form.fields["assigned_to"].label_from_instance(self.pm))
        self.assertIn(self.pm, DeliverableForm(user=self.pm, project=project).fields["assigned_to"].queryset)

        self.client.force_login(self.pm)
        self.client.post(reverse("projects:task_self_assign", args=[task.pk]))
        self.client.post(reverse("projects:deliverable_self_assign", args=[deliverable.pk]))
        task.refresh_from_db()
        deliverable.refresh_from_db()
        self.assertEqual(task.assigned_to, self.pm)
        self.assertEqual(deliverable.assigned_to, self.pm)

        # A self-assigned PM can start the work.
        self.client.post(reverse("projects:start_task_work", args=[task.pk]))
        self.assertTrue(
            WorkSession.objects.filter(user=self.pm, task=task, status=WorkSessionStatus.ACTIVE).exists()
        )

    def test_employee_cannot_self_assign(self):
        project = Project.objects.create(name="No Claim")
        task = Task.objects.create(project=project, name="Cull")
        self.client.force_login(self.employee)
        response = self.client.post(reverse("projects:task_self_assign", args=[task.pk]))
        self.assertEqual(response.status_code, 403)
        task.refresh_from_db()
        self.assertIsNone(task.assigned_to)

    def test_new_event_without_project_notifies_pms_and_creates_todos(self):
        from events.models import Event

        with self.captureOnCommitCallbacks(execute=True):
            event = Event.objects.create(
                name="Asha Wedding",
                date=timezone.localdate() + timedelta(days=30),
                owner=self.crm,
            )

        for pm in (self.pm, self.other_pm):
            self.assertTrue(
                Todo.objects.filter(assigned_to=pm, event=event, status="pending").exists()
            )
            self.assertTrue(
                Notification.objects.filter(
                    recipient=pm, notif_type=Notification.Type.EVENT_NEEDS_PROJECT
                ).exists()
            )
        self.assertFalse(Todo.objects.filter(assigned_to=self.crm, event=event).exists())

        # Creating the project from the event closes those to-dos.
        self.client.force_login(self.pm)
        self.client.post(
            reverse("projects:project_create") + f"?event={event.pk}",
            {
                "name": "Asha Wedding",
                "event": event.pk,
                "status": ProjectStatus.PLANNED,
                "priority": "medium",
            },
        )
        event.refresh_from_db()
        self.assertIsNotNone(event.project)
        self.assertFalse(
            Todo.objects.filter(event=event, status__in=["pending", "in_progress"]).exists()
        )

    def test_event_with_project_creates_no_todo(self):
        from events.models import Event

        project = Project.objects.create(name="Linked")
        with self.captureOnCommitCallbacks(execute=True):
            event = Event.objects.create(name="Linked Event", date=timezone.localdate(), project=project)
        self.assertFalse(Todo.objects.filter(event=event).exists())

    def test_project_calendar_shows_work_with_assignee(self):
        today = timezone.localdate()
        project = Project.objects.create(name="Calendar Project", manager=self.pm)
        Task.objects.create(project=project, name="Edit teaser", due_date=today, assigned_to=self.employee)
        Deliverable.objects.create(project=project, name="Album", due_date=today, assigned_to=self.pm)
        Task.objects.create(project=project, name="Hidden task", due_date=today, assigned_to=self.pm)

        self.client.force_login(self.pm)
        html = self.client.get(reverse("events:event_calendar")).content.decode()
        self.assertIn("Edit teaser", html)
        self.assertIn("Album", html)
        self.assertIn("emp-one", html)

        # Employees see only their own work.
        self.client.force_login(self.employee)
        html = self.client.get(reverse("events:event_calendar")).content.decode()
        self.assertIn("Edit teaser", html)
        self.assertNotIn("Hidden task", html)

        response = self.client.get(reverse("events:event_calendar"), {"month": "bad"})
        self.assertEqual(response.status_code, 200)

        # The old work calendar address opens the one calendar with its filters.
        response = self.client.get(reverse("projects:project_calendar"), {"show": "tasks"})
        self.assertRedirects(response, reverse("events:event_calendar") + "?show=tasks")
