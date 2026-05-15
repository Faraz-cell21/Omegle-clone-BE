import json
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.session_id = str(uuid.uuid4())

        await self.accept()

        await self.send(text_data=json.dumps({
            "type": "session_created",
            "session_id": self.session_id,
        }))

        print(f"Connected: {self.session_id}")

    async def disconnect(self, close_code):
        print(f"Disconnected: {self.session_id}")

    async def receive(self, text_data):
        data = json.loads(text_data)

        message = data.get("message", "")

        await self.send(text_data=json.dumps({
            "type": "message",
            "message": message,
        }))