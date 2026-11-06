"""Verify Telegram WebApp initData and issue short-lived, signed sessions."""
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl
from fastapi import HTTPException


def _secret(name):
    value = os.getenv(name, "")
    if not value:
        raise HTTPException(503, f"{name} is not configured")
    return value


def verify_init_data(raw: str) -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if not token:
        raise HTTPException(503, "Telegram bot token is not configured")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=32)
        fields = dict(pairs)
        if len(pairs) != len(fields):
            raise ValueError("duplicate field")
        supplied = fields.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        expected = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("invalid signature")
        age = time.time() - int(fields["auth_date"])
        if age < -30 or age > 300:
            raise ValueError("expired")
        user = json.loads(fields["user"])
        user_id = user["id"]
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("invalid user")
        return user_id
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "Invalid or expired Telegram authentication")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_session(user_id: str) -> str:
    key = _secret("SESSION_SECRET")
    if len(key) < 32:
        raise HTTPException(503, "SESSION_SECRET must be at least 32 characters")
    payload = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + 3600}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_session(token: str) -> str:
    key = _secret("SESSION_SECRET")
    if len(key) < 32:
        raise HTTPException(503, "SESSION_SECRET must be at least 32 characters")
    try:
        payload, signature = token.split(".")
        expected = _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise ValueError("signature")
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(data["sub"], str) or data["exp"] <= time.time():
            raise ValueError("expired")
        return data["sub"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "Invalid or expired session")
