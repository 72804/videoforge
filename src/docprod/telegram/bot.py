from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from docprod.telegram.client import TelegramClient

START_TEXT = (
    "Create AI videos from a prompt, characters and a few settings."
)
HELP_TEXT = (
    "Open the studio, describe a video, add optional characters, then pay with Telegram Stars. "
    "Generation is currently a mock preview of the finished product flow."
)
LOCAL_STUDIO_NOTE = (
    "The Mini App is only on this machine for now. Telegram cannot open localhost "
    "as a Web App, so there is no Open Studio button yet."
)


def public_https_mini_app_url(mini_app_url: str) -> str:
    """Telegram Web App buttons require a public https URL. Localhost is never valid."""
    raw = (mini_app_url or "").strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return ""
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return ""
    return raw


def studio_keyboard(mini_app_url: str) -> dict[str, Any] | None:
    url = public_https_mini_app_url(mini_app_url)
    if not url:
        return None
    return {"inline_keyboard": [[{"text": "Open Video Studio", "web_app": {"url": url}}]]}


def project_keyboard(mini_app_url: str, project_id: str | None) -> dict[str, Any] | None:
    url = public_https_mini_app_url(mini_app_url)
    if not url:
        return None
    target = f"{url.rstrip('/')}/projects/{project_id}" if project_id else url
    return {"inline_keyboard": [[{"text": "Open Project", "web_app": {"url": target}}]]}


def command_text(base: str, mini_app_url: str) -> str:
    if public_https_mini_app_url(mini_app_url):
        return base
    return f"{base}\n\n{LOCAL_STUDIO_NOTE}"


def handle_command(
    telegram: TelegramClient,
    *,
    chat_id: int,
    text: str,
    mini_app_url: str,
) -> None:
    command = text.strip().split()[0].split("@", 1)[0].lower() if text.strip() else ""
    keyboard = studio_keyboard(mini_app_url)
    if command in {"/start", "/studio"}:
        telegram.send_message(
            chat_id,
            command_text(START_TEXT, mini_app_url),
            reply_markup=keyboard,
        )
        return
    if command == "/help":
        telegram.send_message(
            chat_id,
            command_text(HELP_TEXT, mini_app_url),
            reply_markup=keyboard,
        )
        return
    telegram.send_message(
        chat_id,
        command_text("Use /start to open Video Studio.", mini_app_url),
        reply_markup=keyboard,
    )
