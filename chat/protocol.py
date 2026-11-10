"""Wire-format constants, validation rules, and frame helpers."""

import json
import re
from datetime import datetime, timezone

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,19}$")
ROOM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,29}$")
MAX_LINE = 8192
MAX_TEXT = 2000
DEFAULT_ROOM = "lobby"
ALLOWED_EMOJI = ("👍", "❤️", "😂", "🎉", "🚀", "👀", "🔥", "💡")

ROOM_RULE = "Room must be 1-30 letters, digits, underscore or hyphen, starting with a letter"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def packet(_kind, **fields):
    """Build an outgoing frame. Explicit fields (including ``time``) win over defaults."""
    return {"type": _kind, "time": now_iso(), **fields}


def encode(item):
    return (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")


def valid_text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT


def valid_room(value):
    return isinstance(value, str) and ROOM_RE.fullmatch(value) is not None


def valid_name(value):
    return isinstance(value, str) and NAME_RE.fullmatch(value) is not None


def valid_message_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def valid_emoji(value):
    return isinstance(value, str) and value in ALLOWED_EMOJI
