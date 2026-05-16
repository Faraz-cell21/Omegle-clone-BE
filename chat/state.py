from collections import defaultdict, deque
import time


MAX_BUFFER_MESSAGES = 100


room_messages = defaultdict(
    lambda: deque(maxlen=MAX_BUFFER_MESSAGES)
)


reports = []


def add_room_message(room_id, message_data):

    room_messages[room_id].append({
        **message_data,
        "timestamp": time.time(),
    })


def get_room_messages(room_id):

    return list(room_messages.get(room_id, []))


def clear_room_messages(room_id):

    if room_id in room_messages:
        del room_messages[room_id]


def create_report(report_data):

    reports.append(report_data)