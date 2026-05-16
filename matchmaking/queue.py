from collections import deque
import uuid

global_queue = deque()

def add_to_queue(consumer):
    if global_queue:
        partner = global_queue.popleft()

        room_id = str(uuid4())

        return {
            "matched": True,
            "partner": partner,
            "room_id": room_id,
        }
    
    global_queue.append(consumer)
    
    return {
        "matched": False,
    }