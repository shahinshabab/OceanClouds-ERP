# common/consumers.py

import asyncio

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db.models import Q
from django.utils import timezone

from common.live import GROUP_ADMINS, GROUP_INQUIRIES, session_tag, user_group
from common.models import UserLoginSession
from common.roles import ROLE_ADMIN, can_access_inquiry, user_has_role

# Close codes the browser script treats as "do not reconnect".
CLOSE_SESSION_ENDED = 4401


class LiveUpdatesConsumer(AsyncJsonWebsocketConsumer):
    """
    One socket per open tab. It only receives pushes; it never counts as
    activity, so it does not affect presence, attendance, or session deadlines.
    """

    async def connect(self):
        self.groups_joined = []
        self.expiry_task = None

        user = self.scope.get("user")
        session = self.scope.get("session")
        session_key = getattr(session, "session_key", None)
        if not user or not user.is_authenticated or not session_key:
            await self.close(code=CLOSE_SESSION_ENDED)
            return

        expires_at, groups = await self._load_access(user, session_key)
        if expires_at is False:
            await self.close(code=CLOSE_SESSION_ENDED)
            return

        self.session_tag = session_tag(session_key)
        for group in groups:
            await self.channel_layer.group_add(group, self.channel_name)
            self.groups_joined.append(group)

        await self.accept()

        if expires_at is not None:
            delay = max(0, (expires_at - timezone.now()).total_seconds())
            self.expiry_task = asyncio.create_task(self._close_after(delay))

    async def disconnect(self, code):
        if self.expiry_task:
            self.expiry_task.cancel()
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Clients only listen; ignore anything they send.
        return

    async def live_event(self, event):
        payload = event["payload"]
        kind = payload.get("kind")
        if kind == "session_ended":
            if payload.get("session") == self.session_tag:
                await self.close(code=CLOSE_SESSION_ENDED)
            return
        if kind == "session_replaced":
            if payload.get("keep") != self.session_tag:
                await self.close(code=CLOSE_SESSION_ENDED)
            return
        await self.send_json(payload)

    async def _close_after(self, delay):
        await asyncio.sleep(delay)
        await self.close(code=CLOSE_SESSION_ENDED)

    @database_sync_to_async
    def _load_access(self, user, session_key):
        """
        Returns (expires_at, groups), or (False, []) when this browser's login
        is closed or past its fixed deadline.
        """
        now = timezone.now()
        login = (
            UserLoginSession.objects.filter(
                user_id=user.pk,
                session_key=session_key,
                logout_at__isnull=True,
            )
            .filter(Q(expires_at__gt=now) | Q(expires_at__isnull=True))
            .only("expires_at")
            .first()
        )
        if login is None:
            return False, []

        groups = [user_group(user.pk)]
        if can_access_inquiry(user):
            groups.append(GROUP_INQUIRIES)
        if user_has_role(user, ROLE_ADMIN):
            groups.append(GROUP_ADMINS)
        return login.expires_at, groups
