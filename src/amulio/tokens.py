import base64
import hashlib
import hmac
import json
import time
from typing import Any


class InvalidToken(ValueError):
    pass


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign(payload: dict[str, Any], *, secret: str, ttl_seconds: int) -> str:
    body = {**payload, "exp": int(time.time()) + ttl_seconds}
    encoded_body = _encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode(), encoded_body.encode(), hashlib.sha256).digest()
    return f"{encoded_body}.{_encode(signature)}"


def verify(token: str, *, secret: str) -> dict[str, Any]:
    try:
        encoded_body, encoded_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded_body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(encoded_signature)):
            raise InvalidToken("invalid signature")
        payload = json.loads(_decode(encoded_body))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidToken("malformed token") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("exp"), int):
        raise InvalidToken("malformed payload")
    if payload["exp"] < time.time():
        raise InvalidToken("expired token")
    return payload
