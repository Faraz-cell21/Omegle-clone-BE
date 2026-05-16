import json
import uuid
import asyncio
import time

from channels.generic.websocket import AsyncWebsocketConsumer

from matchmaking.queue import (
    add_to_queue,
    remove_from_queue,
    normalize_tags,
    fallback_global_match,
)

from chat.state import (
    add_room_message,
    get_room_messages,
    clear_room_messages,
    create_report,
)


HEARTBEAT_INTERVAL = 15
HEARTBEAT_TIMEOUT = 30

MESSAGE_RATE_LIMIT = 5
QUEUE_JOIN_COOLDOWN = 3


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):

        self.session_id = str(uuid.uuid4())

        self.room_id = None
        self.tags = []
        self.is_waiting = False

        self.last_heartbeat = time.time()

        self.message_timestamps = []

        self.last_queue_join = 0

        await self.accept()

        self.client_ip = self.scope.get("client", ["unknown"])[0]

        headers = dict(self.scope["headers"])

        self.user_agent = (
            headers.get(b"user-agent", b"")
            .decode()
        )

        await self.send(text_data=json.dumps({
            "type": "session_created",
            "session_id": self.session_id,
        }))

        asyncio.create_task(
            self.monitor_heartbeat()
        )

        print(f"Connected: {self.session_id}")

    async def disconnect(self, close_code):

        if self.is_waiting:
            remove_from_queue(self)

        if self.room_id:

            await self.channel_layer.group_send(
                self.room_id,
                {
                    "type": "partner_disconnected",
                }
            )

            await self.channel_layer.group_discard(
                self.room_id,
                self.channel_name,
            )

            clear_room_messages(self.room_id)

        print(f"Disconnected: {self.session_id}")

    async def receive(self, text_data):

        data = json.loads(text_data)

        event_type = data.get("type")

        if event_type == "join_queue":
            await self.handle_join_queue(data)

        elif event_type == "message":
            await self.handle_message(data)

        elif event_type == "skip":
            await self.handle_skip()

        elif event_type == "heartbeat":
            await self.handle_heartbeat()

        elif event_type == "report":
            await self.handle_report(data)

    async def handle_heartbeat(self):

        self.last_heartbeat = time.time()

        await self.send(text_data=json.dumps({
            "type": "heartbeat_ack",
        }))

    async def monitor_heartbeat(self):

        while True:

            await asyncio.sleep(HEARTBEAT_INTERVAL)

            current_time = time.time()

            if (
                current_time - self.last_heartbeat
                > HEARTBEAT_TIMEOUT
            ):

                print(
                    f"Heartbeat timeout: {self.session_id}"
                )

                await self.close()

                break

    async def handle_join_queue(self, data):

        current_time = time.time()

        if (
            current_time - self.last_queue_join
            < QUEUE_JOIN_COOLDOWN
        ):

            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Queue join cooldown active.",
            }))

            return

        self.last_queue_join = current_time

        raw_tags = data.get("tags", [])

        self.tags = normalize_tags(raw_tags)
        self.is_waiting = True

        result = add_to_queue(self)

        if result["matched"]:

            await self.create_match(
                result["partner"],
                result["room_id"],
                result["matched_tags"],
            )

            return

        await self.send(text_data=json.dumps({
            "type": "waiting",
            "message": "Searching for users with matching interests...",
            "tags": self.tags,
        }))

        asyncio.create_task(
            self.handle_global_fallback()
        )

    async def handle_global_fallback(self):

        await asyncio.sleep(10)

        if not self.is_waiting:
            return

        result = fallback_global_match(self)

        if result["matched"]:

            await self.create_match(
                result["partner"],
                result["room_id"],
                [],
            )

            return

        await self.send(text_data=json.dumps({
            "type": "waiting",
            "message": "Still searching globally...",
        }))

    async def create_match(
        self,
        partner,
        room_id,
        matched_tags,
    ):

        self.room_id = room_id
        partner.room_id = room_id

        self.is_waiting = False
        partner.is_waiting = False

        self.matched_tags = matched_tags

        await self.channel_layer.group_add(
            room_id,
            self.channel_name
        )

        await partner.channel_layer.group_add(
            room_id,
            partner.channel_name
        )

        await self.channel_layer.group_send(
            room_id,
            {
                "type": "match_found",
                "room_id": room_id,
                "matched_tags": matched_tags,
            }
        )

    async def handle_message(self, data):

        if not self.room_id:
            return

        current_time = time.time()

        self.message_timestamps = [
            ts
            for ts in self.message_timestamps
            if current_time - ts < 1
        ]

        if len(self.message_timestamps) >= MESSAGE_RATE_LIMIT:

            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Message rate limit exceeded.",
            }))

            return

        self.message_timestamps.append(current_time)

        message = data.get("message")

        message_data = {
            "sender": self.session_id,
            "message": message,
        }

        add_room_message(
            self.room_id,
            message_data,
        )

        await self.channel_layer.group_send(
            self.room_id,
            {
                "type": "chat_message",
                **message_data,
            }
        )

    async def handle_report(self, data):

        if not self.room_id:
            return

        reason = data.get(
            "reason",
            "No reason provided",
        )

        report_data = {
            "report_id": str(uuid.uuid4()),
            "room_id": self.room_id,
            "reporter_session": self.session_id,
            "reason": reason,
            "matched_tags": self.matched_tags,
            "messages": get_room_messages(
                self.room_id
            ),
            "metadata": {
                "ip_address": self.client_ip,
                "user_agent": self.user_agent,
            },
            "timestamp": time.time(),
        }

        create_report(report_data)

        await self.send(text_data=json.dumps({
            "type": "report_submitted",
        }))

        print(
            f"REPORT CREATED: {report_data}"
        )

    async def handle_skip(self):

        if not self.room_id:
            return

        room_id = self.room_id

        await self.channel_layer.group_send(
            room_id,
            {
                "type": "partner_skipped",
            }
        )

        await self.channel_layer.group_discard(
            room_id,
            self.channel_name,
        )

        clear_room_messages(room_id)

        self.room_id = None

        await self.handle_join_queue({
            "tags": self.tags
        })

    async def chat_message(self, event):

        await self.send(text_data=json.dumps({
            "type": "message",
            "message": event["message"],
            "sender": event["sender"],
        }))

    async def match_found(self, event):

        await self.send(text_data=json.dumps({
            "type": "matched",
            "room_id": event["room_id"],
            "matched_tags": event["matched_tags"],
        }))

    async def partner_disconnected(self, event):

        self.room_id = None

        await self.send(text_data=json.dumps({
            "type": "partner_disconnected",
        }))

    async def partner_skipped(self, event):

        self.room_id = None

        await self.send(text_data=json.dumps({
            "type": "partner_skipped",
            "message": "Partner skipped the chat.",
        }))