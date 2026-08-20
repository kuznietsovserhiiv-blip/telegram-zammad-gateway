import logging
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.i18n import SUPPORTED_LOCALES, text


logger = logging.getLogger("telegram_gateway.telegram")


@dataclass(frozen=True)
class TelegramFile:
    filename: str
    mime_type: str
    content: bytes


COMMANDS = {"default": (("start", "start"), ("help", "help")), "customer": (("new", "new"), ("mytickets", "mytickets"), ("current", "current"), ("close", "close"), ("help", "help")), "admin": (("my", "my"), ("newtickets", "newtickets"), ("ticket", "ticket"), ("current", "current"), ("close", "close"), ("help", "help"))}


def commands_for_mode(mode: str, locale: str = "uk") -> list[dict[str, str]]:
    return [{"command": command, "description": text(locale, label)} for command, label in COMMANDS.get(mode, COMMANDS["default"])]


def keyboard_for_mode(mode: str, locale: str = "uk") -> dict | None:
    rows = {"customer": (("button_new", "button_mytickets"), ("button_current", "button_close"), ("button_help",)), "admin": (("button_my", "button_newtickets"), ("button_ticket", "button_current"), ("button_close", "button_help"))}.get(mode)
    if rows is None:
        return None
    return {"keyboard": [[{"text": text(locale, item)} for item in row] for row in rows], "resize_keyboard": True, "is_persistent": True}


def new_ticket_force_reply(locale: str) -> dict:
    return {"force_reply": True, "input_field_placeholder": text(locale, "new_placeholder")}


def ticket_number_force_reply(locale: str) -> dict:
    return {"force_reply": True, "input_field_placeholder": text(locale, "ticket_placeholder")}


async def download_file(
    settings: Settings,
    file_id: str,
    *,
    filename: str,
    mime_type: str,
    max_bytes: int,
) -> TelegramFile:
    """Resolve and download Telegram media while enforcing a size limit."""
    base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        metadata = await client.get(f"{base_url}/getFile", params={"file_id": file_id})
        metadata.raise_for_status()
        payload = metadata.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        file_path = result.get("file_path") if isinstance(result, dict) else None
        file_size = result.get("file_size") if isinstance(result, dict) else None
        if not isinstance(file_path, str) or not file_path:
            raise ValueError("Telegram did not return a file path")
        if isinstance(file_size, int) and file_size > max_bytes:
            raise ValueError("Telegram file is too large")
        response = await client.get(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}")
        response.raise_for_status()
        if len(response.content) > max_bytes:
            raise ValueError("Telegram file is too large")
        return TelegramFile(
            filename=filename[:255] or "telegram-file",
            mime_type=mime_type[:255] or "application/octet-stream",
            content=response.content,
        )


async def send_message(
    settings: Settings,
    chat_id: int,
    text: str,
    *,
    reply_markup: dict | None = None,
) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        payload: dict = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = await client.post(url, json=payload)
        response.raise_for_status()


async def safe_send_message(
    settings: Settings,
    chat_id: int,
    text: str,
    *,
    reply_markup: dict | None = None,
) -> None:
    try:
        await send_message(settings, chat_id, text, reply_markup=reply_markup)
    except httpx.HTTPError:
        logger.exception("Telegram sendMessage failed for chat_id=%s", chat_id)


async def answer_callback_query(
    settings: Settings,
    callback_query_id: str,
    *,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/answerCallbackQuery"
    payload: dict = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert,
    }
    if text:
        payload["text"] = text
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


async def safe_answer_callback_query(
    settings: Settings,
    callback_query_id: str,
    *,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    try:
        await answer_callback_query(
            settings,
            callback_query_id,
            text=text,
            show_alert=show_alert,
        )
    except httpx.HTTPError:
        logger.exception("Telegram answerCallbackQuery failed for id=%s", callback_query_id)


async def set_commands(
    settings: Settings,
    commands: list[dict[str, str]],
    *,
    chat_id: int | None = None,
    language_code: str | None = None,
) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/setMyCommands"
    payload: dict = {"commands": commands}
    if chat_id is not None:
        payload["scope"] = {"type": "chat", "chat_id": chat_id}
    if language_code is not None:
        payload["language_code"] = language_code
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("ok") is not True:
            raise httpx.HTTPStatusError(
                "Telegram rejected setMyCommands",
                request=response.request,
                response=response,
            )


async def safe_set_chat_commands(settings: Settings, chat_id: int, mode: str) -> None:
    try:
        for locale in SUPPORTED_LOCALES:
            await set_commands(settings, commands_for_mode(mode, locale), chat_id=chat_id, language_code=locale)
    except (httpx.HTTPError, ValueError):
        logger.exception("Telegram setMyCommands failed for chat_id=%s mode=%s", chat_id, mode)


async def get_default_commands(settings: Settings) -> list[dict[str, str]]:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMyCommands"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json={"scope": {"type": "default"}})
        response.raise_for_status()
        data = response.json()
        if data.get("ok") is not True or not isinstance(data.get("result"), list):
            raise RuntimeError("Telegram returned invalid getMyCommands response")
        return data["result"]
