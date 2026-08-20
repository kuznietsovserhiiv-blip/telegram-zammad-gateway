import logging
import json
import secrets
import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import Settings, get_settings
from app.database import get_db
from app.link_service import (
    LinkConflictError,
    bind_telegram_user,
    consume_link_token,
    find_active_telegram_link,
)
from app.session_service import (
    clear_chat_session,
    clear_pending_action,
    get_chat_session,
    get_pending_action,
    remember_telegram_ticket,
    set_chat_session,
    set_pending_action,
)
from app.models import TelegramUpdate
from app.security import read_limited_body
from app.telegram_client import (
    keyboard_for_mode,
    new_ticket_force_reply,
    safe_answer_callback_query,
    safe_send_message,
    safe_set_chat_commands,
    ticket_number_force_reply,
    download_file,
)
from app.i18n import SUPPORTED_LOCALES, locale_from_telegram, text as tr
from app.zammad import ZammadApi, ZammadApiError


logger = logging.getLogger("telegram_gateway.telegram")
router = APIRouter(prefix="/telegram", tags=["telegram"])

BUTTON_COMMANDS = {
    tr(locale, key): command
    for locale in SUPPORTED_LOCALES
    for key, command in {
        "button_new": "/new", "button_mytickets": "/mytickets",
        "button_current": "/current", "button_close": "/close",
        "button_help": "/help", "button_my": "/my",
        "button_newtickets": "/newtickets", "button_ticket": "/ticket",
    }.items()
}


def telegram_configured(settings: Settings) -> bool:
    return (
        settings.telegram_bot_token not in {"", "replace_me"}
        and settings.telegram_webhook_secret not in {"", "replace_me"}
    )


def user_mode(user: dict, settings: Settings) -> str:
    if user.get("active") is False:
        return "denied"
    role_ids = {int(value) for value in user.get("role_ids", [])}
    if settings.zammad_admin_role_id in role_ids:
        return "admin"
    if settings.zammad_customer_role_id in role_ids:
        return "customer"
    if settings.zammad_agent_role_id in role_ids:
        return "agent_disabled"
    return "denied"


def reserve_telegram_update(db: Session, update_id: object) -> bool:
    """Return False when Telegram is retrying an update already accepted by us."""
    try:
        normalized_id = int(update_id)
    except (TypeError, ValueError):
        return True
    db.add(TelegramUpdate(update_id=normalized_id, received_at=int(time.time())))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def customer_can_access_ticket(ticket: dict, zammad_user_id: int) -> bool:
    customer_value = ticket.get("customer_id") or ticket.get("customer") or 0
    if isinstance(customer_value, dict):
        customer_value = customer_value.get("id") or 0
    try:
        ticket_customer_id = int(customer_value)
    except (TypeError, ValueError):
        ticket_customer_id = 0
    state = ticket.get("state")
    if isinstance(state, dict):
        state = state.get("name")
    closed_states = {"closed", "merged", "removed"}
    return ticket_customer_id == zammad_user_id and str(state or "").strip().lower() not in closed_states


def customer_open_tickets(tickets: list[dict], zammad_user_id: int) -> list[dict]:
    return [
        ticket
        for ticket in tickets
        if customer_can_access_ticket(ticket, zammad_user_id)
    ][:20]


def command_name(text: str) -> tuple[str, str]:
    button_command = BUTTON_COMMANDS.get(text.strip())
    if button_command:
        return button_command, ""
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower() if parts else ""
    argument = parts[1].strip() if len(parts) == 2 else ""
    return command, argument


def ticket_title(body: str) -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "Telegram request")
    return first_line[:120]


def attachment_media(message: dict) -> tuple[dict, str] | None:
    """Return supported Telegram media and its update-field name."""
    for kind in ("document", "video", "video_note", "audio", "voice"):
        media = message.get(kind)
        if isinstance(media, dict):
            return media, kind
    photo = message.get("photo")
    if isinstance(photo, list) and photo:
        media = max(
            (item for item in photo if isinstance(item, dict)),
            key=lambda item: int(item.get("file_size") or 0),
            default=None,
        )
        if media is not None:
            return media, "photo"
    return None


def zammad_search_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def format_ticket_list(
    heading: str,
    tickets: list[dict],
    *,
    footer: str | None = "Вибрати заявку: /ticket <номер>",
) -> str:
    if not tickets:
        return f"{heading}\n\nЗаявок не знайдено."

    lines = [heading, ""]
    current_length = len(heading) + 2
    for ticket in tickets:
        number = str(ticket.get("number") or "?")
        title = " ".join(str(ticket.get("title") or "Без назви").split())[:160]
        state = str(ticket.get("state") or "—")
        group = str(ticket.get("group") or "—")
        owner = str(ticket.get("owner") or "—")
        item = f"#{number} · {state} · {group}\n{title}\nВідповідальний: {owner}"
        if current_length + len(item) + 2 > 3800:
            lines.append("…список скорочено")
            break
        lines.extend([item, ""])
        current_length += len(item) + 2
    if footer:
        lines.append(footer)
    return "\n".join(lines)


def ticket_inline_keyboard(tickets: list[dict]) -> dict:
    rows: list[list[dict[str, str]]] = []
    for ticket in tickets:
        try:
            ticket_id = int(ticket["id"])
        except (KeyError, TypeError, ValueError):
            continue
        number = str(ticket.get("number") or "?")
        state = str(ticket.get("state") or "—")
        title = " ".join(str(ticket.get("title") or "Без назви").split())
        label = f"#{number} · {state} · {title}"
        if len(label) > 72:
            label = label[:69].rstrip() + "…"
        rows.append(
            [
                {
                    "text": label,
                    "callback_data": f"select_ticket:{ticket_id}",
                }
            ]
        )
    return {"inline_keyboard": rows}


def help_text(mode: str, locale: str = "uk") -> str:
    if mode == "customer":
        if locale == "en":
            return (
                "Commands:\n/new <issue description> — create a ticket\n"
                "/mytickets — my open tickets\n/current — current ticket\n"
                "/close — close the current conversation"
            )
        if locale == "ru":
            return (
                "Команды:\n/new <описание проблемы> — создать заявку\n"
                "/mytickets — мои незакрытые заявки\n/current — текущая заявка\n"
                "/close — завершить текущий диалог"
            )
        return (
            "Команди:\n"
            "/new <опис проблеми> — створити заявку\n"
            "/mytickets — мої незакриті заявки\n"
            "/current — поточна заявка\n"
            "/close — завершити поточний діалог"
        )
    if mode == "admin":
        if locale == "en":
            return (
                "Commands:\n/my — my active tickets\n/newtickets — all new tickets\n"
                "/ticket <number> — select a ticket\n/current — current ticket\n"
                "/close — close the current conversation"
            )
        if locale == "ru":
            return (
                "Команды:\n/my — мои активные заявки\n/newtickets — все новые заявки\n"
                "/ticket <номер> — выбрать заявку\n/current — текущая заявка\n"
                "/close — завершить текущий диалог"
            )
        return (
            "Команди:\n"
            "/my — мої активні заявки\n"
            "/newtickets — усі нові заявки\n"
            "/ticket <номер> — вибрати заявку\n"
            "/current — поточна заявка\n"
            "/close — завершити поточний діалог"
        )
    if locale == "en":
        return "Your Telegram access mode is not supported yet."
    return "Ваш режим работы с Telegram пока не поддерживается." if locale == "ru" else "Ваш режим роботи з Telegram поки не реалізований."


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    if not telegram_configured(settings):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Telegram is not configured")
    if not x_telegram_bot_api_secret_token or not secrets.compare_digest(
        x_telegram_bot_api_secret_token, settings.telegram_webhook_secret
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret")
    body = await read_limited_body(request, settings.webhook_max_body_bytes)
    try:
        update = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc
    if not isinstance(update, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")
    if not reserve_telegram_update(db, update.get("update_id")):
        return {"ok": True}

    callback_query = update.get("callback_query")
    callback_query_id: str | None = None
    callback_data: str | None = None
    if isinstance(callback_query, dict):
        message = callback_query.get("message")
        sender = callback_query.get("from") or {}
        callback_query_id = str(callback_query.get("id") or "")
        callback_data = callback_query.get("data")
        text = ""
    else:
        message = update.get("message")
        sender = message.get("from") if isinstance(message, dict) else {}
        text = (message.get("text") or message.get("caption") or "") if isinstance(message, dict) else None
    if not isinstance(message, dict):
        return {"ok": True}
    chat = message.get("chat") or {}
    media_item = attachment_media(message)
    media = media_item[0] if media_item else None
    if (
        chat.get("type") != "private"
        or not isinstance(sender, dict)
        or sender.get("is_bot")
        or not isinstance(text, str)
        or (callback_data is None and not text and not isinstance(media, dict))
        or (callback_query_id is not None and not isinstance(callback_data, str))
    ):
        return {"ok": True}

    try:
        telegram_user_id = int(sender["id"])
        telegram_chat_id = int(chat["id"])
    except (KeyError, TypeError, ValueError):
        return {"ok": True}
    locale = locale_from_telegram(sender.get("language_code"))

    if callback_query_id:
        await safe_answer_callback_query(settings, callback_query_id)

    command, argument = command_name(text) if callback_data is None else ("", "")
    if command == "/start" and argument:
        token_row = consume_link_token(db, token=argument)
        if token_row is None:
            db.rollback()
            await safe_send_message(settings, telegram_chat_id, "Код недійсний, уже використаний або минув термін дії. Створіть новий код у профілі Zammad.")
            return {"ok": True}
        try:
            bind_telegram_user(
                db,
                link_token=token_row,
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                telegram_username=sender.get("username"),
            )
            db.commit()
        except LinkConflictError as exc:
            db.rollback()
            await safe_send_message(settings, telegram_chat_id, str(exc))
            return {"ok": True}
        linked_mode: str | None = None
        try:
            linked_user = await ZammadApi(settings).get_user(token_row.zammad_user_id)
            linked_mode = user_mode(linked_user, settings)
            await safe_set_chat_commands(
                settings,
                telegram_chat_id,
                linked_mode,
            )
        except ZammadApiError:
            logger.exception(
                "Unable to set role menu after linking Zammad user id=%s",
                token_row.zammad_user_id,
            )
        await safe_send_message(
            settings,
            telegram_chat_id,
            f"Telegram успішно підключено до Zammad: {token_row.zammad_login}",
            reply_markup=keyboard_for_mode(linked_mode or "denied", locale),
        )
        return {"ok": True}

    link = find_active_telegram_link(db, telegram_user_id)
    if link is None:
        await safe_send_message(
            settings,
            telegram_chat_id,
            f"Спочатку підключіть Telegram у Zammad: {settings.public_base_url}/link",
        )
        return {"ok": True}

    api = ZammadApi(settings)
    try:
        zammad_user = await api.get_user(link.zammad_user_id)
    except ZammadApiError:
        logger.exception("Unable to load linked Zammad user id=%s", link.zammad_user_id)
        await safe_send_message(settings, telegram_chat_id, "Zammad тимчасово недоступний. Спробуйте пізніше.")
        return {"ok": True}

    mode = user_mode(zammad_user, settings)
    if mode in {"agent_disabled", "denied"}:
        await safe_set_chat_commands(settings, telegram_chat_id, mode)
        await safe_send_message(settings, telegram_chat_id, help_text(mode, locale))
        return {"ok": True}

    attachment: tuple[str, str, bytes] | None = None
    if isinstance(media, dict):
        file_id = media.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            await safe_send_message(settings, telegram_chat_id, "Не вдалося визначити файл Telegram.")
            return {"ok": True}
        media_kind = media_item[1]
        if media_kind == "voice":
            default_filename, default_mime = "telegram-voice.ogg", "audio/ogg"
        elif media_kind == "audio":
            default_filename, default_mime = "telegram-audio.mp3", "audio/mpeg"
        elif media_kind == "video_note":
            default_filename, default_mime = "telegram-video-note.mp4", "video/mp4"
        elif media_kind == "video":
            default_filename, default_mime = "telegram-video.mp4", "video/mp4"
        elif media_kind == "photo":
            default_filename, default_mime = "telegram-photo.jpg", "image/jpeg"
        else:
            default_filename, default_mime = "telegram-file", "application/octet-stream"
        try:
            downloaded = await download_file(
                settings,
                file_id,
                filename=str(media.get("file_name") or default_filename),
                mime_type=str(media.get("mime_type") or default_mime),
                max_bytes=settings.telegram_file_max_bytes,
            )
        except (ValueError, httpx.HTTPError):
            logger.exception("Unable to download Telegram media")
            max_size_mb = settings.telegram_file_max_bytes / (1024 * 1024)
            await safe_send_message(settings, telegram_chat_id, f"Не вдалося завантажити файл. Максимальний розмір файла — {max_size_mb:g} МБ.")
            return {"ok": True}
        attachment = (downloaded.filename, downloaded.mime_type, downloaded.content)

    if callback_data is not None:
        prefix = "select_ticket:"
        if not callback_data.startswith(prefix):
            await safe_send_message(settings, telegram_chat_id, "Невідома дія. Оновіть список заявок.")
            return {"ok": True}
        try:
            ticket_id = int(callback_data[len(prefix) :])
            ticket = await api.get_ticket(ticket_id)
        except (ValueError, ZammadApiError):
            logger.exception("Unable to select ticket from callback data=%s", callback_data)
            await safe_send_message(settings, telegram_chat_id, "Заявка недоступна або вже видалена.")
            return {"ok": True}

        if mode == "customer":
            if not customer_can_access_ticket(ticket, link.zammad_user_id):
                await safe_send_message(settings, telegram_chat_id, "Ця заявка закрита або не належить вашому профілю.")
                return {"ok": True}

        set_chat_session(
            db,
            telegram_user_id=telegram_user_id,
            mode=mode,
            zammad_ticket_id=int(ticket["id"]),
            ticket_number=str(ticket["number"]),
            ticket_title=str(ticket["title"]),
        )
        clear_pending_action(db, telegram_user_id)
        await safe_send_message(
            settings,
            telegram_chat_id,
            f"Вибрано заявку #{ticket['number']}: {ticket['title']}\n"
            "Наступні звичайні повідомлення буде додано до цієї заявки.",
        )
        return {"ok": True}

    if command in {"/start", "/help"}:
        clear_pending_action(db, telegram_user_id)
        await safe_set_chat_commands(settings, telegram_chat_id, mode)
        await safe_send_message(
            settings,
            telegram_chat_id,
            help_text(mode, locale),
            reply_markup=keyboard_for_mode(mode, locale),
        )
        return {"ok": True}

    if command == "/current":
        clear_pending_action(db, telegram_user_id)
        session = get_chat_session(db, telegram_user_id)
        if session is None:
            await safe_send_message(settings, telegram_chat_id, "Поточну заявку не вибрано.\n" + help_text(mode, locale))
        else:
            await safe_send_message(
                settings,
                telegram_chat_id,
                f"Поточна заявка #{session.ticket_number}: {session.ticket_title}",
            )
        return {"ok": True}

    if command == "/close":
        clear_pending_action(db, telegram_user_id)
        cleared = clear_chat_session(db, telegram_user_id)
        message_text = "Поточний діалог завершено. Стан заявки в Zammad не змінено." if cleared else "Поточну заявку не вибрано."
        await safe_send_message(settings, telegram_chat_id, message_text)
        return {"ok": True}

    if mode == "customer":
        if command == "/mytickets":
            clear_pending_action(db, telegram_user_id)
            try:
                tickets = await api.search_tickets(
                    f"customer_id:{link.zammad_user_id}", per_page=100
                )
                tickets = customer_open_tickets(tickets, link.zammad_user_id)
            except ZammadApiError:
                logger.exception("Unable to list customer tickets for Zammad user id=%s", link.zammad_user_id)
                await safe_send_message(settings, telegram_chat_id, "Не вдалося отримати ваші заявки із Zammad.")
                return {"ok": True}
            await safe_send_message(
                settings,
                telegram_chat_id,
                (
                    f"Мої незакриті заявки ({len(tickets)}, до 20):\n"
                    "Натисніть заявку, щоб зробити її поточною."
                    if tickets
                    else "Незакритих заявок не знайдено."
                ),
                reply_markup=ticket_inline_keyboard(tickets) if tickets else None,
            )
            return {"ok": True}
        pending = get_pending_action(db, telegram_user_id)
        pending_description = pending is not None and pending.action == "customer_new"
        if command == "/new" or (pending_description and not command.startswith("/")) or (
            attachment is not None and get_chat_session(db, telegram_user_id) is None
        ):
            description = argument if command == "/new" else text.strip()
            if attachment and not description:
                await safe_send_message(settings, telegram_chat_id, "Додайте короткий опис файлу в полі підпису та надішліть його ще раз.")
                return {"ok": True}
            if not description:
                set_pending_action(
                    db,
                    telegram_user_id=telegram_user_id,
                    action="customer_new",
                )
                await safe_send_message(
                    settings,
                    telegram_chat_id,
                    "Опишіть проблему одним повідомленням. Воно стане описом нової заявки.",
                    reply_markup=new_ticket_force_reply(locale),
                )
                return {"ok": True}
            organization_id = zammad_user.get("organization_id")
            if not organization_id:
                await safe_send_message(settings, telegram_chat_id, "Для вашого профілю не вказана організація. Зверніться до адміністратора.")
                return {"ok": True}
            try:
                organization = await api.get_organization(int(organization_id))
                group_value = organization.get("telegram_group")
                group_id = int(group_value) if group_value not in {None, ""} else 0
            except (ZammadApiError, TypeError, ValueError):
                logger.exception("Unable to resolve support group for organization id=%s", organization_id)
                await safe_send_message(settings, telegram_chat_id, "Для вашої організації не налаштована група підтримки.")
                return {"ok": True}
            if group_id <= 0:
                await safe_send_message(settings, telegram_chat_id, "Для вашої організації не налаштована група підтримки.")
                return {"ok": True}
            title = ticket_title(description)
            try:
                ticket = await api.create_customer_ticket(
                    user_id=link.zammad_user_id,
                    group_id=group_id,
                    title=title,
                    body=description,
                    attachments=[attachment] if attachment else None,
                )
            except ZammadApiError:
                logger.exception("Unable to create ticket for Zammad user id=%s", link.zammad_user_id)
                await safe_send_message(settings, telegram_chat_id, "Не вдалося створити заявку в Zammad. Зверніться до адміністратора.")
                return {"ok": True}
            set_chat_session(
                db,
                telegram_user_id=telegram_user_id,
                mode="customer",
                zammad_ticket_id=int(ticket["id"]),
                ticket_number=str(ticket["number"]),
                ticket_title=str(ticket["title"]),
            )
            remember_telegram_ticket(
                db,
                zammad_ticket_id=int(ticket["id"]),
                ticket_number=str(ticket["number"]),
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                zammad_customer_id=link.zammad_user_id,
                group_id=group_id,
            )
            clear_pending_action(db, telegram_user_id)
            await safe_send_message(settings, telegram_chat_id, f"Заявку #{ticket['number']} створено: {ticket['title']}")
            return {"ok": True}
        if command.startswith("/"):
            await safe_send_message(settings, telegram_chat_id, help_text(mode, locale))
            return {"ok": True}
        session = get_chat_session(db, telegram_user_id)
        if session is None or session.mode != "customer":
            await safe_send_message(settings, telegram_chat_id, "Спочатку створіть заявку.\n" + help_text(mode, locale))
            return {"ok": True}
        try:
            ticket = await api.get_ticket(session.zammad_ticket_id)
            if not customer_can_access_ticket(ticket, link.zammad_user_id):
                clear_chat_session(db, telegram_user_id)
                await safe_send_message(
                    settings,
                    telegram_chat_id,
                    "Заявка закрита або більше не належить вашому профілю. Поточний діалог завершено.",
                )
                return {"ok": True}
            await api.add_article(
                ticket_id=session.zammad_ticket_id,
                user_id=link.zammad_user_id,
                body=text.strip() or "Вкладення з Telegram",
                sender="Customer",
                article_type="web",
                attachments=[attachment] if attachment else None,
            )
        except ZammadApiError:
            logger.exception("Unable to add customer article ticket_id=%s", session.zammad_ticket_id)
            await safe_send_message(settings, telegram_chat_id, "Не вдалося додати повідомлення до заявки.")
            return {"ok": True}
        await safe_send_message(settings, telegram_chat_id, f"Повідомлення додано до заявки #{session.ticket_number}.")
        return {"ok": True}

    if mode == "admin":
        if command == "/my":
            clear_pending_action(db, telegram_user_id)
            owner_email = str(zammad_user.get("email") or zammad_user.get("login") or "")
            query = (
                f'owner.email:"{zammad_search_value(owner_email)}" '
                "AND state.name:(new OR open OR pending*)"
            )
            try:
                tickets = await api.search_tickets(query, per_page=20)
            except ZammadApiError:
                logger.exception("Unable to list active tickets for Zammad user id=%s", link.zammad_user_id)
                await safe_send_message(settings, telegram_chat_id, "Не вдалося отримати ваші заявки із Zammad.")
                return {"ok": True}
            await safe_send_message(
                settings,
                telegram_chat_id,
                (
                    f"Мої активні заявки ({len(tickets)}, до 20):\n"
                    "Натисніть заявку, щоб зробити її поточною."
                    if tickets
                    else "Активних заявок не знайдено."
                ),
                reply_markup=ticket_inline_keyboard(tickets) if tickets else None,
            )
            return {"ok": True}
        if command == "/newtickets":
            clear_pending_action(db, telegram_user_id)
            try:
                tickets = await api.search_tickets("state.name:new", per_page=20)
            except ZammadApiError:
                logger.exception("Unable to list new Zammad tickets")
                await safe_send_message(settings, telegram_chat_id, "Не вдалося отримати нові заявки із Zammad.")
                return {"ok": True}
            await safe_send_message(
                settings,
                telegram_chat_id,
                (
                    f"Усі нові заявки ({len(tickets)}, до 20):\n"
                    "Натисніть заявку, щоб зробити її поточною."
                    if tickets
                    else "Нових заявок не знайдено."
                ),
                reply_markup=ticket_inline_keyboard(tickets) if tickets else None,
            )
            return {"ok": True}
        pending = get_pending_action(db, telegram_user_id)
        pending_ticket_number = pending is not None and pending.action == "admin_ticket"
        if command == "/ticket" or (pending_ticket_number and not command.startswith("/")):
            ticket_number = argument if command == "/ticket" else text.strip()
            if not ticket_number:
                set_pending_action(
                    db,
                    telegram_user_id=telegram_user_id,
                    action="admin_ticket",
                )
                await safe_send_message(
                    settings,
                    telegram_chat_id,
                    "Введіть номер заявки, яку потрібно вибрати.",
                    reply_markup=ticket_number_force_reply(locale),
                )
                return {"ok": True}
            if not ticket_number.replace("-", "").isalnum():
                await safe_send_message(settings, telegram_chat_id, "Некоректний номер заявки. Спробуйте ще раз.")
                return {"ok": True}
            try:
                ticket = await api.find_ticket_by_number(ticket_number)
            except ZammadApiError:
                logger.exception("Unable to search ticket number=%s", ticket_number)
                await safe_send_message(settings, telegram_chat_id, "Не вдалося виконати пошук у Zammad.")
                return {"ok": True}
            if ticket is None:
                await safe_send_message(settings, telegram_chat_id, f"Заявку #{ticket_number} не знайдено або вона недоступна.")
                return {"ok": True}
            set_chat_session(
                db,
                telegram_user_id=telegram_user_id,
                mode="admin",
                zammad_ticket_id=int(ticket["id"]),
                ticket_number=str(ticket["number"]),
                ticket_title=str(ticket["title"]),
            )
            clear_pending_action(db, telegram_user_id)
            await safe_send_message(settings, telegram_chat_id, f"Вибрано заявку #{ticket['number']}: {ticket['title']}")
            return {"ok": True}
        if command.startswith("/"):
            await safe_send_message(settings, telegram_chat_id, help_text(mode, locale))
            return {"ok": True}
        session = get_chat_session(db, telegram_user_id)
        if session is None or session.mode != "admin":
            await safe_send_message(settings, telegram_chat_id, "Спочатку виберіть заявку.\n" + help_text(mode, locale))
            return {"ok": True}
        try:
            await api.add_article(
                ticket_id=session.zammad_ticket_id,
                user_id=link.zammad_user_id,
                body=text.strip() or "Вкладення з Telegram",
                sender="Agent",
                article_type="note",
                attachments=[attachment] if attachment else None,
            )
        except ZammadApiError:
            logger.exception("Unable to add admin article ticket_id=%s", session.zammad_ticket_id)
            await safe_send_message(settings, telegram_chat_id, "Не вдалося додати повідомлення до заявки.")
            return {"ok": True}
        await safe_send_message(settings, telegram_chat_id, f"Коментар додано до заявки #{session.ticket_number} від вашого імені.")
    return {"ok": True}
