import json
import uuid
import asyncio
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from django.conf import settings
from django.utils import timezone
# from datetime import timedelta

from matchmaking.queue import (
    add_to_queue,
    remove_from_queue,
    normalize_tags,
)

from moderation.models import (
    # Report,
    TemporaryBan,
)

from core.redis import redis_client
from core.turnstile import is_ip_captcha_verified


HEARTBEAT_INTERVAL = 15
HEARTBEAT_TIMEOUT = 30

MESSAGE_RATE_LIMIT = 5
QUEUE_JOIN_COOLDOWN = 3
SKIP_LIMIT_PER_MINUTE = 12
SKIP_COOLDOWN_SECONDS = 30

# REPORT_BAN_THRESHOLD = 3


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
        self._presence_key = f"presence:{self.session_id}"
        self._active_ip_count_key = f"active_ip_count:{self.client_ip}"

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

        self._register_ip_presence()

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
            await self._notify_partner_disconnected()
            await self._discard_room_membership()

        self._unregister_ip_presence()

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

        # elif event_type == "report":
        #     await self.handle_report(data)

    async def handle_heartbeat(self):

        self.last_heartbeat = time.time()

        redis_client.set(
            self._presence_key,
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
                await self.send(text_data=json.dumps({
                    "type": "timeout",
                    "message": "Connection timed out due to inactivity.",
                }))

                await self.close()

                break

    async def _notify_partner_disconnected(self):

        if not self.room_id:
            return

        await self.channel_layer.group_send(
            self.room_id,
            {
                "type": "partner_disconnected",
                "excluded_session": self.session_id,
            },
        )

    async def _discard_room_membership(self):

        if not self.room_id:
            return

        room_id = self.room_id

        await self.channel_layer.group_discard(
            room_id,
            self.channel_name,
        )

        redis_client.delete(
            f"room:{room_id}:messages"
        )

        self.room_id = None

    async def leave_current_room(self):

        if not self.room_id:
            return

        await self._notify_partner_disconnected()
        await self._discard_room_membership()

    async def handle_join_queue(self, data):

        if not is_ip_captcha_verified(self.client_ip):
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Complete security verification before connecting.",
            }))
            return

        is_skip_request = bool(self.room_id)

        if self.room_id:
            await self.leave_current_room()

        if await self._skip_limit_triggered(is_skip_request):
            return

        bypass_limits = getattr(settings, "LOAD_TEST_BYPASS_LIMITS", False)
        cooldown_key = f"cooldown:{self.client_ip}"

        if not bypass_limits and redis_client.exists(cooldown_key):
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Queue cooldown active.",
            }))
            return

        if not bypass_limits:
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

    async def _skip_limit_triggered(self, is_skip_request):
        if not is_skip_request:
            return False

        if getattr(settings, "LOAD_TEST_BYPASS_LIMITS", False):
            return False

        if self.client_ip == "unknown":
            return False

        skip_block_key = f"skip:block:{self.client_ip}"
        if redis_client.exists(skip_block_key):
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": f"Skip cooldown active. Wait {SKIP_COOLDOWN_SECONDS}s.",
            }))
            return True

        skip_count_key = f"skip:count:{self.client_ip}"
        count = redis_client.incr(skip_count_key)
        if count == 1:
            redis_client.expire(skip_count_key, 60)

        if count > SKIP_LIMIT_PER_MINUTE:
            redis_client.set(
                skip_block_key,
                "1",
                ex=SKIP_COOLDOWN_SECONDS,
            )
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": f"Too many skips. Wait {SKIP_COOLDOWN_SECONDS}s.",
            }))
            return True

        return False

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

    # async def handle_report(self, data):
    #
    #     if not self.room_id:
    #         return
    #
    #     messages = redis_client.lrange(
    #         f"room:{self.room_id}:messages",
    #         0,
    #         -1,
    #     )
    #
    #     parsed_messages = [
    #         json.loads(msg)
    #         for msg in messages
    #     ]
    #
    #     await self.submit_report(
    #         reason=data.get(
    #             "reason",
    #             "No reason",
    #         ),
    #         parsed_messages=parsed_messages,
    #     )
    #
    #     await self.send(text_data=json.dumps({
    #         "type":
    #         "report_submitted",
    #     }))

    @database_sync_to_async
    def is_ip_banned(self):
        return TemporaryBan.objects.filter(
            ip_address=self.client_ip,
            expires_at__gt=timezone.now(),
        ).exists()

    def _register_ip_presence(self):
        if self.client_ip == "unknown":
            return

        redis_client.sadd("visited_ips", self.client_ip)
        count = redis_client.incr(self._active_ip_count_key)
        if count == 1:
            redis_client.sadd("active_ips", self.client_ip)

    def _unregister_ip_presence(self):
        if self.client_ip == "unknown":
            return

        count = redis_client.decr(self._active_ip_count_key)
        if count <= 0:
            redis_client.delete(self._active_ip_count_key)
            redis_client.srem("active_ips", self.client_ip)

    # @database_sync_to_async
    # def submit_report(self, reason, parsed_messages):
    #     Report.objects.create(
    #         report_id=str(uuid.uuid4()),
    #         room_id=self.room_id,
    #         reporter_session=self.session_id,
    #         reason=reason,
    #         matched_tags=self.tags,
    #         messages=parsed_messages,
    #         metadata={
    #             "ip": self.client_ip,
    #             "user_agent": self.user_agent,
    #         },
    #     )
    #
    #     report_count = Report.objects.filter(
    #         metadata__ip=self.client_ip,
    #     ).count()
    #
    #     if report_count >= REPORT_BAN_THRESHOLD:
    #         TemporaryBan.objects.get_or_create(
    #             ip_address=self.client_ip,
    #             defaults={
    #                 "reason": "Too many reports",
    #                 "expires_at": timezone.now() + timedelta(hours=24),
    #             },
    #         )

    async def partner_disconnected(self, event):

        if (
            event.get("excluded_session")
            == self.session_id
        ):
            return

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
