import uuid
import json

from core.redis import redis_client


WAITING_USERS_KEY = "waiting_users"


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

    waiting_users = redis_client.lrange(
        WAITING_USERS_KEY,
        0,
        -1,
    )

    best_match = None
    best_overlap = []

    for raw_user in waiting_users:

        waiting_user = json.loads(raw_user)

        if (
            waiting_user["session_id"]
            == consumer.session_id
        ):
            continue

        overlap = calculate_overlap(
            consumer.tags,
            waiting_user["tags"],
        )

        if len(overlap) > len(best_overlap):
            best_overlap = overlap
            best_match = waiting_user

    if best_match:

        redis_client.lrem(
            WAITING_USERS_KEY,
            1,
            json.dumps(best_match),
        )

        room_id = str(uuid.uuid4())

        return {
            "matched": True,
            "partner_session":
            best_match["session_id"],
            "partner_channel_name":
            best_match["channel_name"],
            "room_id": room_id,
            "matched_tags": best_overlap,
        }

    redis_client.rpush(
        WAITING_USERS_KEY,
        json.dumps({
            "session_id":
            consumer.session_id,
            "channel_name":
            consumer.channel_name,
            "tags":
            consumer.tags,
        })
    )

    return {
        "matched": False,
    }


def remove_from_queue(session_id):

    waiting_users = redis_client.lrange(
        WAITING_USERS_KEY,
        0,
        -1,
    )

    for raw_user in waiting_users:

        waiting_user = json.loads(raw_user)

        if waiting_user["session_id"] == session_id:

            redis_client.lrem(
                WAITING_USERS_KEY,
                1,
                raw_user,
            )