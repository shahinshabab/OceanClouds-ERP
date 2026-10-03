import json
from datetime import timedelta

from asgiref.sync import sync_to_async
from asgiref.testing import ApplicationCommunicator
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from common.models import Notification, UserLoginSession
from common.notifications import notify_user
from common.session_management import close_expired_login_sessions
from common.roles import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_PROJECT_MANAGER
from common.test_helpers import make_user
from core.asgi import application
from crm.models import Inquiry
from projects.models import Project, Task
from todos.models import Todo


def make_role_user(username, role):
    user = make_user(username=username)
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def logged_in_client(user):
    client = Client()
    client.force_login(user)
    return client


class LiveSocket:
    """
    Websocket test client for one login. Built on asgiref directly because
    channels.testing needs daphne, which production does not install.
    """

    def __init__(self, client=None):
        headers = [(b"origin", b"http://testserver"), (b"host", b"testserver")]
        if client is not None:
            cookie = f"{settings.SESSION_COOKIE_NAME}={client.session.session_key}"
            headers.append((b"cookie", cookie.encode()))
        self.communicator = ApplicationCommunicator(application, {
            "type": "websocket",
            "path": "/ws/live/",
            "raw_path": b"/ws/live/",
            "query_string": b"",
            "headers": headers,
            "subprotocols": [],
        })

    async def connect(self):
        await self.communicator.send_input({"type": "websocket.connect"})
        output = await self.communicator.receive_output(2)
        if output["type"] == "websocket.accept":
            return True, None
        return False, output.get("code")

    async def output(self, timeout=1):
        return await self.communicator.receive_output(timeout)

    async def receive(self, kind=None, timeout=1):
        """Next JSON payload, skipping other kinds when one is given."""
        while True:
            output = await self.output(timeout)
            assert output["type"] == "websocket.send", output
            payload = json.loads(output["text"])
            if kind is None or payload["kind"] == kind:
                return payload

    async def nothing(self, timeout=0.2):
        return await self.communicator.receive_nothing(timeout)

    async def close(self):
        await self.communicator.send_input({"type": "websocket.disconnect", "code": 1000})
        await self.communicator.wait(1)


class LiveUpdatesTests(TransactionTestCase):
    def setUp(self):
        self.employee = make_role_user("live-employee", ROLE_EMPLOYEE)
        self.other_employee = make_role_user("live-other", ROLE_EMPLOYEE)
        self.admin = make_role_user("live-admin", ROLE_ADMIN)
        self.manager = make_role_user("live-manager", ROLE_PROJECT_MANAGER)

    async def open_socket(self, user):
        client = await sync_to_async(logged_in_client)(user)
        socket = LiveSocket(client)
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        return client, socket

    async def test_anonymous_socket_is_rejected(self):
        connected, code = await LiveSocket().connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_expired_login_is_rejected(self):
        client = await sync_to_async(logged_in_client)(self.employee)
        await UserLoginSession.objects.filter(user=self.employee).aupdate(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        connected, code = await LiveSocket(client).connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_notification_reaches_only_its_recipient(self):
        _, mine = await self.open_socket(self.employee)
        _, theirs = await self.open_socket(self.other_employee)

        await sync_to_async(notify_user)(
            recipient=self.employee,
            notif_type=Notification.Type.TASK_DUE,
            message="Colour grading is due",
        )

        payload = await mine.receive()
        self.assertEqual(payload["kind"], "notification")
        self.assertEqual(payload["action"], "created")
        self.assertEqual(payload["message"], "Colour grading is due")
        self.assertTrue(await theirs.nothing())
        await mine.close()
        await theirs.close()

    async def test_new_inquiry_reaches_inquiry_roles(self):
        _, socket = await self.open_socket(self.employee)

        inquiry = await Inquiry.objects.acreate(name="Anu", channel="instagram")

        payload = await socket.receive()
        self.assertEqual(payload["kind"], "inquiry")
        self.assertEqual(payload["action"], "created")
        self.assertEqual(payload["id"], inquiry.pk)
        self.assertEqual(payload["label"], "Anu")
        self.assertEqual(payload["channel"], "Instagram DM")
        await socket.close()

    async def test_task_updates_follow_task_visibility(self):
        _, admin = await self.open_socket(self.admin)
        _, manager = await self.open_socket(self.manager)
        _, assignee = await self.open_socket(self.employee)
        _, other = await self.open_socket(self.other_employee)

        project = await Project.objects.acreate(name="Wedding film", manager=self.manager)
        task = await Task.objects.acreate(
            project=project, name="Edit teaser", assigned_to=self.employee
        )

        for socket in (admin, manager, assignee):
            payload = await socket.receive(kind="task")
            self.assertEqual(payload["id"], task.pk)
            self.assertEqual(payload["project_id"], project.pk)
        self.assertTrue(await other.nothing())

        # Reassigning also tells the previous assignee, so their list updates.
        task.assigned_to = self.other_employee
        await task.asave()
        payload = await assignee.receive(kind="task")
        self.assertEqual(payload["action"], "updated")
        payload = await other.receive(kind="task")
        self.assertEqual(payload["id"], task.pk)

        for socket in (admin, manager, assignee, other):
            await socket.close()

    async def test_todo_updates_reach_owner_and_assignee_only(self):
        _, owner = await self.open_socket(self.employee)
        _, other = await self.open_socket(self.other_employee)

        await Todo.objects.acreate(
            title="Call vendor", owner=self.employee, assigned_to=self.employee
        )

        payload = await owner.receive(kind="todo")
        self.assertEqual(payload["label"], "Call vendor")
        self.assertTrue(await other.nothing())
        await owner.close()
        await other.close()

    async def test_logout_closes_that_browsers_socket(self):
        client, socket = await self.open_socket(self.employee)

        await sync_to_async(client.post)(reverse("ui:logout"))

        self.assertEqual(await socket.receive(), {"kind": "session_ended", "reason": "logout"})
        output = await socket.output()
        self.assertEqual(output["type"], "websocket.close")
        self.assertEqual(output["code"], 4401)

    async def test_new_login_closes_replaced_browsers_socket(self):
        _, old_socket = await self.open_socket(self.employee)

        await sync_to_async(logged_in_client)(self.employee)

        self.assertEqual(
            await old_socket.receive(),
            {"kind": "session_ended", "reason": "session_replaced"},
        )
        output = await old_socket.output()
        self.assertEqual(output["type"], "websocket.close")

    async def test_idle_login_is_rejected(self):
        client = await sync_to_async(logged_in_client)(self.employee)
        await UserLoginSession.objects.filter(user=self.employee).aupdate(
            last_activity_at=timezone.now() - timedelta(hours=1)
        )
        connected, code = await LiveSocket(client).connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_idle_cleanup_tells_the_page_and_closes_its_socket(self):
        _, socket = await self.open_socket(self.employee)
        await UserLoginSession.objects.filter(user=self.employee).aupdate(
            last_activity_at=timezone.now() - timedelta(hours=1)
        )

        await sync_to_async(close_expired_login_sessions)()

        self.assertEqual(await socket.receive(), {"kind": "session_ended", "reason": "idle_timeout"})
        output = await socket.output()
        self.assertEqual(output["type"], "websocket.close")
        self.assertEqual(output["code"], 4401)


class NotificationPanelTests(TransactionTestCase):
    def test_returns_badge_count_and_html(self):
        user = make_role_user("panel-user", ROLE_EMPLOYEE)
        client = logged_in_client(user)
        notify_user(
            recipient=user,
            notif_type=Notification.Type.TASK_DUE,
            message="Export album",
        )

        response = client.get(reverse("common:notification_panel"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertIn("Export album", data["html"])
