from collections import deque
import uuid


queues = {
    "react": deque(),
    "python": deque(),
}


def get_queue(tag: str):

    if tag not in queues:
        queues[tag] = deque()

    return queues[tag]


def add_to_queue(tag: str, consumer):

    queue = get_queue(tag)

    while queue:

        partner = queue.popleft()

        if partner.channel_name != consumer.channel_name:

            room_id = str(uuid.uuid4())

            return {
                "matched": True,
                "partner": partner,
                "room_id": room_id,
            }

    queue.append(consumer)

    return {
        "matched": False,
    }


def remove_from_queue(tag: str, consumer):

    queue = get_queue(tag)

    updated_queue = deque()

    while queue:

        queued_consumer = queue.popleft()

        if queued_consumer.channel_name != consumer.channel_name:
            updated_queue.append(queued_consumer)

    queues[tag] = updated_queue