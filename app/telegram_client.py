import logging

import httpx

from app.config import Settings


logger = logging.getLogger("telegram_gateway.telegram")


DEFAULT_COMMANDS = [
    {"command": "start", "description": "Почати роботу"},
    {"command": "help", "description": "Показати доступні команди"},
]

CUSTOMER_COMMANDS = [
    {"command": "new", "description": "Створити нову заявку"},
    {"command": "mytickets", "description": "Мої незакриті заявки"},
    {"command": "current", "description": "Показати поточну заявку"},
    {"command": "close", "description": "Завершити поточний діалог"},
    {"command": "help", "description": "Показати доступні команди"},
]

ADMIN_COMMANDS = [
    {"command": "my", "description": "Мої активні заявки"},
    {"command": "newtickets", "description": "Усі нові заявки"},
    {"command": "ticket", "description": "Вибрати заявку за номером"},
    {"command": "current", "description": "Показати поточну заявку"},
    {"command": "close", "description": "Завершити поточний діалог"},
    {"command": "help", "description": "Показати доступні команди"},
]

CUSTOMER_KEYBOARD = {
    "keyboard": [
        [{"text": "📝 Нова заявка"}, {"text": "📋 Мої незакриті заявки"}],
        [{"text": "📌 Поточна заявка"}, {"text": "✅ Завершити діалог"}],
        [{"text": "ℹ️ Допомога"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

ADMIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📋 Мої заявки"}, {"text": "🆕 Нові заявки"}],
        [{"text": "🔎 Вибрати заявку"}, {"text": "📌 Поточна заявка"}],
        [{"text": "✅ Завершити діалог"}, {"text": "ℹ️ Допомога"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

NEW_TICKET_FORCE_REPLY = {
    "force_reply": True,
    "input_field_placeholder": "Опишіть проблему",
}

TICKET_NUMBER_FORCE_REPLY = {
    "force_reply": True,
    "input_field_placeholder": "Введіть номер заявки",
}


def commands_for_mode(mode: str) -> list[dict[str, str]]:
    if mode == "customer":
        return CUSTOMER_COMMANDS
    if mode == "admin":
        return ADMIN_COMMANDS
    return DEFAULT_COMMANDS


def keyboard_for_mode(mode: str) -> dict | None:
    if mode == "customer":
        return CUSTOMER_KEYBOARD
    if mode == "admin":
        return ADMIN_KEYBOARD
    return None


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
) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/setMyCommands"
    payload: dict = {"commands": commands}
    if chat_id is not None:
        payload["scope"] = {"type": "chat", "chat_id": chat_id}
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
        await set_commands(settings, commands_for_mode(mode), chat_id=chat_id)
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
