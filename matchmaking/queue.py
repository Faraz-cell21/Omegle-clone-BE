import uuid
import time


waiting_users = []


def normalize_tags(tags):

    return list(
        set(
            tag.strip().lower()
            for tag in tags
            if tag.strip()
        )
    )


def calculate_overlap(tags1, tags2):

    return list(set(tags1) & set(tags2))


def add_to_queue(consumer):

    best_match = None
    best_overlap = []

    for waiting_consumer in waiting_users:

        if waiting_consumer.channel_name == consumer.channel_name:
            continue

        overlap = calculate_overlap(
            consumer.tags,
            waiting_consumer.tags
        )

        if len(overlap) > len(best_overlap):
            best_overlap = overlap
            best_match = waiting_consumer

    if best_match:

        waiting_users.remove(best_match)

        room_id = str(uuid.uuid4())

        return {
            "matched": True,
            "partner": best_match,
            "room_id": room_id,
            "matched_tags": best_overlap,
        }

    waiting_users.append(consumer)

    return {
        "matched": False,
    }


def remove_from_queue(consumer):

    global waiting_users

    waiting_users = [
        user
        for user in waiting_users
        if user.channel_name != consumer.channel_name
    ]


def fallback_global_match(consumer):

    for waiting_consumer in waiting_users:

        if waiting_consumer.channel_name == consumer.channel_name:
            continue

        waiting_users.remove(waiting_consumer)

        room_id = str(uuid.uuid4())

        return {
            "matched": True,
            "partner": waiting_consumer,
            "room_id": room_id,
            "matched_tags": [],
        }

    return {
        "matched": False,
    }