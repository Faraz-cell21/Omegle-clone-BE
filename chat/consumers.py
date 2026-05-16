import json
import uuid
import asyncio

from channels.generic.websocket import AsyncWebsocketConsumer

from matchmaking.queue import (
    add_to_queue,
    remove_from_queue,
    normalize_tags,
    fallback_global_match,
)


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):

        self.session_id = str(uuid.uuid4())
        self.room_id = None
        self.tags = []
        self.is_waiting = False

        await self.accept()

        await self.send(text_data=json.dumps({
            "type": "session_created",
            "session_id": self.session_id,
        }))

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

    async def handle_join_queue(self, data):

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

        message = data.get("message")

        await self.channel_layer.group_send(
            self.room_id,
            {
                "type": "chat_message",
                "message": message,
                "sender": self.session_id,
            }
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