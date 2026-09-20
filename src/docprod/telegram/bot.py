from __future__ import annotations

from typing import Any

from docprod.telegram.client import TelegramClient

START_TEXT = (
    "Create AI videos from a prompt, characters and a few settings."
)
HELP_TEXT = (
    "Open the studio, describe a video, add optional characters, then pay with Telegram Stars. "
    "Generation is currently a mock preview of the finished product flow."
)


def studio_keyboard(mini_app_url: str) -> dict[str, Any] | None:
    url = mini_app_url.strip()
    if not url:
        return None
    return {"inline_keyboard": [[{"text": "Open Video Studio", "web_app": {"url": url}}]]}


def project_keyboard(mini_app_url: str, project_id: str | None) -> dict[str, Any] | None:
    url = mini_app_url.strip()
    if not url:
        return None
    target = f"{url.rstrip('/')}/projects/{project_id}" if project_id else url
    return {"inline_keyboard": [[{"text": "Open Project", "web_app": {"url": target}}]]}


def handle_command(
    telegram: TelegramClient,
    *,
    chat_id: int,
    text: str,
    mini_app_url: str,
) -> None:
    command = text.strip().split()[0].split("@", 1)[0].lower() if text.strip() else ""
    if command in {"/start", "/studio"}:
        telegram.send_message(chat_id, START_TEXT, reply_markup=studio_keyboard(mini_app_url))
        return
    if command == "/help":
        telegram.send_message(chat_id, HELP_TEXT, reply_markup=studio_keyboard(mini_app_url))
        return
    telegram.send_message(
        chat_id,
        "Use /start to open Video Studio.",
        reply_markup=studio_keyboard(mini_app_url),
    )
