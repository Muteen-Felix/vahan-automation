"""Preserve browser state strings that PostgreSQL JSONB cannot represent."""
import json

_ENCODING = "vahan-user-state-json-text-v1"


def _contains_nul(value):
    if isinstance(value, str):
        return "\0" in value
    if isinstance(value, dict):
        return any(_contains_nul(key) or _contains_nul(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    return False


def encode_user_state(value):
    if not _contains_nul(value):
        return value
    # A JSON string containing escaped JSON is valid JSONB. Decode it on read
    # so existing browser office keys and retry queues remain exactly intact.
    return {"__encoding": _ENCODING, "json": json.dumps(value, ensure_ascii=True)}


def decode_user_state(value):
    if (isinstance(value, dict) and set(value) == {"__encoding", "json"}
            and value["__encoding"] == _ENCODING and isinstance(value["json"], str)):
        return json.loads(value["json"])
    return value
