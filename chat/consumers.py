import json
import uuid
import asyncio
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from django.utils import timezone
from datetime import timedelta

from matchmaking.queue import (
    add_to_queue,
    remove_from_queue,
    normalize_tags,
)

from moderation.models import (
    Report,
    TemporaryBan,
)

from core.redis import redis_client


HEARTBEAT_INTERVAL = 15
HEARTBEAT_TIMEOUT = 30

MESSAGE_RATE_LIMIT = 5
QUEUE_JOIN_COOLDOWN = 3

REPORT_BAN_THRESHOLD = 3


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):

        self.session_id = str(uuid.uuid4())

        self.room_id = None
        self.tags = []
        self.is_waiting = False

        self.last_heartbeat = time.time()

        await self.accept()

        self.client_ip = self.scope.get(
            "client",
            ["unknown"]
        )[0]

        headers = dict(self.scope["headers"])

        self.user_agent = (
            headers.get(
                b"user-agent",
                b"",
            ).decode()
        )

        banned = await self.is_ip_banned()

        if banned:

            await self.send(text_data=json.dumps({
                "type": "banned",
            }))

            await self.close()

            return

        await self.send(text_data=json.dumps({
            "type": "session_created",
            "session_id": self.session_id,
        }))

        asyncio.create_task(
            self.monitor_heartbeat()
        )

    async def disconnect(self, close_code):

        if self.is_waiting:
            remove_from_queue(
                self.session_id
            )

        if self.room_id:

            await self.channel_layer.group_send(
                self.room_id,
                {
                    "type":
                    "partner_disconnected",
                }
            )

            await self.channel_layer.group_discard(
                self.room_id,
                self.channel_name,
            )

            redis_client.delete(
                f"room:{self.room_id}:messages"
            )

    async def receive(self, text_data):

        data = json.loads(text_data)

        event_type = data.get("type")

        if event_type == "heartbeat":
            await self.handle_heartbeat()

        elif event_type == "join_queue":
            await self.handle_join_queue(data)

        elif event_type == "message":
            await self.handle_message(data)

        elif event_type == "typing":
            await self.handle_typing()

        elif event_type == "report":
            await self.handle_report(data)

    async def handle_heartbeat(self):

        self.last_heartbeat = time.time()

        redis_client.set(
            f"presence:{self.session_id}",
            int(time.time()),
            ex=60,
        )

    async def monitor_heartbeat(self):

        while True:

            await asyncio.sleep(
                HEARTBEAT_INTERVAL
            )

            current_time = time.time()

            if (
                current_time
                - self.last_heartbeat
                > HEARTBEAT_TIMEOUT
            ):

                await self.close()

                break

    async def leave_current_room(self):

        if not self.room_id:
            return

        await self.channel_layer.group_discard(
            self.room_id,
            self.channel_name,
        )

        redis_client.delete(
            f"room:{self.room_id}:messages"
        )

        self.room_id = None

    async def handle_join_queue(self, data):

        if self.room_id:
            await self.leave_current_room()

        cooldown_key = (
            f"cooldown:{self.client_ip}"
        )

        if redis_client.exists(cooldown_key):

            await self.send(text_data=json.dumps({
                "type": "error",
                "message":
                "Queue cooldown active.",
            }))

            return

        redis_client.set(
            cooldown_key,
            "1",
            ex=QUEUE_JOIN_COOLDOWN,
        )

        raw_tags = data.get("tags", [])

        self.tags = normalize_tags(
            raw_tags
        )

        self.is_waiting = True

        result = add_to_queue(self)

        if result.get("matched"):

            self.room_id = result["room_id"]

            self.is_waiting = False

            # Join the room group for message relaying
            await self.channel_layer.group_add(
                self.room_id,
                self.channel_name,
            )

            # Notify the partner who was waiting
            matched_tags = result["matched_tags"]

            await self.channel_layer.send(
                result["partner_channel_name"],
                {
                    "type": "matched_event",
                    "room_id": self.room_id,
                    "partner_session": self.session_id,
                    "matched_tags": matched_tags,
                }
            )

            # Notify self
            await self.send(text_data=json.dumps({
                "type": "matched",
                "room_id": self.room_id,
                "matched_tags": matched_tags,
            }))

        else:

            await self.send(text_data=json.dumps({
                "type": "waiting",
            }))

    async def handle_message(self, data):

        if not self.room_id:
            return

        rate_limit_key = (
            f"rate:{self.session_id}"
        )

        current_count = redis_client.incr(
            rate_limit_key
        )

        if current_count == 1:
            redis_client.expire(
                rate_limit_key,
                1,
            )

        if (
            current_count
            > MESSAGE_RATE_LIMIT
        ):

            await self.send(text_data=json.dumps({
                "type": "error",
                "message":
                "Rate limit exceeded.",
            }))

            return

        message = data.get("message")

        message_data = {
            "sender": self.session_id,
            "message": message,
            "timestamp": time.time(),
        }

        redis_client.rpush(
            f"room:{self.room_id}:messages",
            json.dumps(message_data),
        )

        redis_client.ltrim(
            f"room:{self.room_id}:messages",
            -100,
            -1,
        )

        await self.channel_layer.group_send(
            self.room_id,
            {
                "type": "chat_message",
                **message_data,
            }
        )

    async def handle_typing(self):

        if not self.room_id:
            return

        await self.channel_layer.group_send(
            self.room_id,
            {
                "type": "typing_event",
                "sender":
                self.session_id,
            }
        )

    async def handle_report(self, data):

        if not self.room_id:
            return

        messages = redis_client.lrange(
            f"room:{self.room_id}:messages",
            0,
            -1,
        )

        parsed_messages = [
            json.loads(msg)
            for msg in messages
        ]

        await self.submit_report(
            reason=data.get(
                "reason",
                "No reason",
            ),
            parsed_messages=parsed_messages,
        )

        await self.send(text_data=json.dumps({
            "type":
            "report_submitted",
        }))

    @database_sync_to_async
    def is_ip_banned(self):
        return TemporaryBan.objects.filter(
            ip_address=self.client_ip,
            expires_at__gt=timezone.now(),
        ).exists()

    @database_sync_to_async
    def submit_report(self, reason, parsed_messages):
        Report.objects.create(
            report_id=str(uuid.uuid4()),
            room_id=self.room_id,
            reporter_session=self.session_id,
            reason=reason,
            matched_tags=self.tags,
            messages=parsed_messages,
            metadata={
                "ip": self.client_ip,
                "user_agent": self.user_agent,
            },
        )

        report_count = Report.objects.filter(
            metadata__ip=self.client_ip,
        ).count()

        if report_count >= REPORT_BAN_THRESHOLD:
            TemporaryBan.objects.get_or_create(
                ip_address=self.client_ip,
                defaults={
                    "reason": "Too many reports",
                    "expires_at": timezone.now() + timedelta(hours=24),
                },
            )

    async def partner_disconnected(self, event):

        await self.send(text_data=json.dumps({
            "type": "partner_disconnected",
        }))

    async def matched_event(self, event):

        self.room_id = event["room_id"]

        self.is_waiting = False

        await self.channel_layer.group_add(
            self.room_id,
            self.channel_name,
        )

        await self.send(text_data=json.dumps({
            "type": "matched",
            "room_id": self.room_id,
            "matched_tags":
            event["matched_tags"],
        }))

    async def chat_message(self, event):

        await self.send(text_data=json.dumps({
            "type": "message",
            "message":
            event["message"],
            "sender":
            event["sender"],
        }))

    async def typing_event(self, event):

        if (
            event["sender"]
            == self.session_id
        ):
            return

        await self.send(text_data=json.dumps({
            "type": "typing",
        }))
