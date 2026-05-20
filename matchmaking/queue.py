import uuid
import json

from core.redis import redis_client


WAITING_USERS_KEY = "waiting_users"
RECENT_PARTNERS_KEY_PREFIX = "recent_partners"
RECENT_PARTNER_TTL_SECONDS = 600
RECENT_PARTNER_SET_SIZE = 40


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


def _recent_partners_key(session_id):
    return f"{RECENT_PARTNERS_KEY_PREFIX}:{session_id}"


def _has_recent_match(session_a, session_b):
    if not session_a or not session_b:
        return False
    return bool(
        redis_client.sismember(
            _recent_partners_key(session_a),
            session_b,
        )
    )


def _remember_match_pair(session_a, session_b):
    if not session_a or not session_b:
        return

    key_a = _recent_partners_key(session_a)
    key_b = _recent_partners_key(session_b)

    redis_client.sadd(key_a, session_b)
    redis_client.sadd(key_b, session_a)
    redis_client.expire(key_a, RECENT_PARTNER_TTL_SECONDS)
    redis_client.expire(key_b, RECENT_PARTNER_TTL_SECONDS)

    # Keep sets bounded to avoid unbounded growth.
    if redis_client.scard(key_a) > RECENT_PARTNER_SET_SIZE:
        stale = redis_client.srandmember(key_a)
        if stale:
            redis_client.srem(key_a, stale)
    if redis_client.scard(key_b) > RECENT_PARTNER_SET_SIZE:
        stale = redis_client.srandmember(key_b)
        if stale:
            redis_client.srem(key_b, stale)


def add_to_queue(consumer):

    waiting_users = redis_client.lrange(
        WAITING_USERS_KEY,
        0,
        -1,
    )

    is_global = len(consumer.tags) == 0

    best_match = None
    best_overlap = []
    first_global_match = None

    for raw_user in waiting_users:

        waiting_user = json.loads(raw_user)

        if (
            waiting_user["session_id"]
            == consumer.session_id
        ):
            continue

        if _has_recent_match(
            consumer.session_id,
            waiting_user["session_id"],
        ):
            continue

        waiting_tags = waiting_user["tags"]
        waiting_is_global = len(waiting_tags) == 0

        # Global chat: match with anyone else in global queue (FIFO)
        if is_global:
            if waiting_is_global and first_global_match is None:
                first_global_match = waiting_user
            continue

        # Tagged chat: only match users who also have tags
        if waiting_is_global:
            continue

        overlap = calculate_overlap(
            consumer.tags,
            waiting_tags,
        )

        if len(overlap) > len(best_overlap):
            best_overlap = overlap
            best_match = waiting_user

    if is_global and first_global_match is not None:
        best_match = first_global_match
        best_overlap = []

    if best_match:

        redis_client.lrem(
            WAITING_USERS_KEY,
            1,
            json.dumps(best_match),
        )

        _remember_match_pair(
            consumer.session_id,
            best_match["session_id"],
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
