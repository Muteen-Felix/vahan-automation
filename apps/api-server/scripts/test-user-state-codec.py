"""Run without pytest's database-clearing fixtures: python scripts/test-user-state-codec.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.state_codec import encode_user_state, decode_user_state

recovery = {"status": "stopped", "queueOfficeKeys": ["andaman\0swaraj dweep"],
            "retryQueueIndices": [13, 14, 15], "log": [{"status": "error", "index": 13}]}
encoded = encode_user_state(recovery)
assert encoded != recovery
assert "\0" not in encoded["json"]
assert decode_user_state(json.loads(json.dumps(encoded))) == recovery
for value in [None, 0, False, "plain state", [], {"version": 1}, {"literal": r"\u0000"}]:
    assert encode_user_state(value) == value
    assert decode_user_state(value) == value
for value in ["a\0b", ["a\0b", "a\\u0000b"], {"a\0b": {"value": "x\0y"}}, {"label": "Hà Nội\0東京"}]:
    assert decode_user_state(json.loads(json.dumps(encode_user_state(value)))) == value
assert decode_user_state({"__encoding": "another-format", "json": "{}"}) == {"__encoding": "another-format", "json": "{}"}
print("User-state checks passed: legacy state, literal escapes, nested NUL strings/keys, Unicode and complete retry-queue preservation.")
