import json
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer

from matchmaking.queue import add_to_queue


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.session_id = str(uuid.uuid4())
        self.room_id = None

        await self.accept()

        await self.send(text_data=json.dumps({
            "type": "session_created",
            "session_id": self.session_id,
        }))

        print(f"Connected: {self.session_id}")

    async def disconnect(self, close_code):

        if self.room_id:
            await self.channel_layer.group_send(
                self.room_id,
                {
                    "type": "partner_disconnected",
                }
            )

        print(f"Disconnected: {self.session_id}")

    async def receive(self, text_data):
        data = json.loads(text_data)

        event_type = data.get("type")

        if event_type == "join_queue":
            await self.handle_join_queue()

        elif event_type == "message":
            await self.handle_message(data)

    async def handle_join_queue(self):

        result = add_to_queue(self)

        if result["matched"]:

            partner = result["partner"]
            room_id = result["room_id"]

            self.room_id = room_id
            partner.room_id = room_id

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
                }
            )

        else:
            await self.send(text_data=json.dumps({
                "type": "waiting",
                "message": "Waiting for partner..."
            }))

    async def handle_message(self, data):

        message = data.get("message")

        await self.channel_layer.group_send(
            self.room_id,
            {
                "type": "chat_message",
                "message": message,
                "sender": self.session_id,
            }
        )

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
        }))

    async def partner_disconnected(self, event):

        await self.send(text_data=json.dumps({
            "type": "partner_disconnected",
        }))