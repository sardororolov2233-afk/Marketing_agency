"""Small Telegram webhook adapter; transport and project storage are injected."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable, Mapping
from typing import Any


async def handle_telegram_webhook(
    update: Mapping[str, Any],
    secret: str | None,
    configured_secret: str | None,
    owner_id: int | None,
    list_projects: Callable[[], Awaitable[list[Any]]],
    send_message: Callable[[int, str], Awaitable[None]],
) -> int:
    """Process a Telegram update and return its HTTP response status.

    Set a high-entropy webhook secret and register it with Telegram. Only private
    messages whose sender and chat both match the configured owner are processed.
    Unknown users and non-message updates are acknowledged without a response.
    """
    if not isinstance(configured_secret, str) or not configured_secret:
        return 503
    if not isinstance(secret, str) or not hmac.compare_digest(
        secret.encode("utf-8"), configured_secret.encode("utf-8")
    ):
        return 403
    if not isinstance(update, Mapping):
        return 400
    if not isinstance(owner_id, int) or isinstance(owner_id, bool) or owner_id <= 0:
        return 503

    message = update.get("message")
    if not isinstance(message, Mapping):
        return 200
    sender, chat, text = message.get("from"), message.get("chat"), message.get("text")
    if not isinstance(sender, Mapping) or not isinstance(chat, Mapping):
        return 200
    if (sender.get("id") != owner_id or chat.get("id") != owner_id
            or chat.get("type") != "private" or not isinstance(text, str)):
        return 200

    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.strip() else ""
    if command == "/start":
        reply = "Assalomu alaykum! Marketing agentligi boshqaruv botiga xush kelibsiz. /help"
    elif command == "/help":
        reply = "Buyruqlar:\n/start — botni boshlash\n/projects — loyihalar\n/help — yordam"
    elif command == "/projects":
        projects = await list_projects()
        names = []
        for project in projects[:30]:
            name = project.get("name", "") if isinstance(project, Mapping) else str(project)
            if isinstance(name, str) and name.strip():
                names.append(name.strip().replace("\n", " ")[:100])
        reply = "Loyihalar:\n" + "\n".join(f"• {name}" for name in names) if names else "Hozircha loyihalar yo‘q."
    else:
        reply = "Noma’lum buyruq. Yordam uchun /help ni yuboring."
    await send_message(owner_id, reply)
    return 200
