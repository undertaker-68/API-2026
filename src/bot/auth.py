import os

def is_allowed(chat_id: int) -> bool:
    s = os.environ.get("ALLOWED_CHAT_IDS", "").strip()
    if not s:
        return True
    allowed = {int(x.strip()) for x in s.split(",") if x.strip()}
    return chat_id in allowed
