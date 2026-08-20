import hashlib
import hmac
import json
import logging
import re
import time
from html import unescape
from html.parser import HTMLParser
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.link_service import find_active_zammad_link
from app.models import TicketStateSnapshot, ZammadWebhookDelivery
from app.telegram_client import send_message


logger = logging.getLogger("telegram_gateway.zammad_webhook")
router = APIRouter(prefix="/zammad", tags=["zammad"])
DELIVERY_PROCESSING_TIMEOUT_SECONDS = 5 * 60


class _TextExtractor(HTMLParser):
    block_tags = {"br", "div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.block_tags - {"br"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    text = unescape("".join(parser.parts)).replace("\r", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def valid_signature(body: bytes, supplied: str | None, secret: str) -> bool:
    if not supplied or secret in {"", "replace_me"}:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha1).hexdigest()
    candidate = supplied.strip()
    if candidate.lower().startswith("sha1="):
        candidate = candidate[5:]
    return hmac.compare_digest(candidate.lower(), expected)


def nested_id(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sender_name(article: dict[str, Any]) -> str:
    created_by = article.get("created_by")
    if isinstance(created_by, dict):
        full_name = " ".join(
            str(created_by.get(key) or "").strip() for key in ("firstname", "lastname")
        ).strip()
        return full_name or str(created_by.get("login") or "співробітника підтримки")
    return "співробітника підтримки"


def article_sender(article: dict[str, Any]) -> str:
    value = article.get("sender")
    if isinstance(value, dict):
        value = value.get("name")
    return str(value or "").lower()


def customer_id(ticket: dict[str, Any]) -> int | None:
    return nested_id(ticket.get("customer_id")) or nested_id(ticket.get("customer"))


def owner_id(ticket: dict[str, Any]) -> int | None:
    return nested_id(ticket.get("owner_id")) or nested_id(ticket.get("owner"))


def ticket_state(ticket: dict[str, Any]) -> tuple[str, str] | None:
    value = ticket.get("state")
    state_id = nested_id(ticket.get("state_id"))
    state_name = ""
    if isinstance(value, dict):
        state_id = nested_id(value) or state_id
        state_name = str(value.get("name") or "").strip()
    elif value not in {None, ""}:
        state_name = str(value).strip()
    state_name = state_name or str(ticket.get("state_name") or "").strip()
    if not state_name and state_id is None:
        return None
    state_key = f"id:{state_id}" if state_id is not None else f"name:{state_name.lower()}"
    return state_key, state_name or str(state_id)


def localized_state_name(value: str) -> str:
    translations = {
        "new": "нова",
        "open": "відкрита",
        "pending reminder": "очікує нагадування",
        "pending close": "очікує закриття",
        "closed": "закрита",
        "merged": "об’єднана",
    }
    return translations.get(value.strip().lower(), value)


def update_state_snapshot(
    db: Session,
    *,
    ticket_id: int,
    ticket_number: str,
    state_key: str,
    state_name: str,
) -> None:
    snapshot = (
        db.query(TicketStateSnapshot)
        .where(TicketStateSnapshot.zammad_ticket_id == ticket_id)
        .first()
    )
    now = int(time.time())
    if snapshot is None:
        db.add(
            TicketStateSnapshot(
                zammad_ticket_id=ticket_id,
                ticket_number=ticket_number,
                state_key=state_key,
                state_name=state_name,
                updated_at=now,
            )
        )
    else:
        snapshot.ticket_number = ticket_number
        snapshot.state_key = state_key
        snapshot.state_name = state_name
        snapshot.updated_at = now


def reserve_delivery(
    db: Session,
    delivery_id: str,
    *,
    now: int | None = None,
) -> ZammadWebhookDelivery | None:
    now = now or int(time.time())
    delivery = ZammadWebhookDelivery(
        delivery_id=delivery_id,
        outcome="processing",
        received_at=now,
    )
    db.add(delivery)
    try:
        db.commit()
        return delivery
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(ZammadWebhookDelivery)
            .where(ZammadWebhookDelivery.delivery_id == delivery_id)
            .first()
        )
        if (
            existing is None
            or existing.outcome != "processing"
            or existing.received_at > now - DELIVERY_PROCESSING_TIMEOUT_SECONDS
        ):
            return None
        # A worker died after reserving this delivery. Allow a later retry to
        # take ownership instead of suppressing the notification forever.
        claimed = db.execute(
            update(ZammadWebhookDelivery)
            .where(
                ZammadWebhookDelivery.id == existing.id,
                ZammadWebhookDelivery.outcome == "processing",
                ZammadWebhookDelivery.received_at == existing.received_at,
            )
            .values(received_at=now)
        )
        db.commit()
        if claimed.rowcount != 1:
            return None
        return db.get(ZammadWebhookDelivery, existing.id)


def complete_delivery(db: Session, delivery: ZammadWebhookDelivery, outcome: str) -> None:
    delivery.outcome = outcome
    db.commit()


@router.post("/webhook")
async def zammad_webhook(
    request: Request,
    x_hub_signature: str | None = Header(default=None),
    x_zammad_delivery: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Webhook body is too large")
    if not valid_signature(body, x_hub_signature, settings.zammad_webhook_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature")
    if not x_zammad_delivery:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing delivery ID")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    delivery = reserve_delivery(db, x_zammad_delivery)
    if delivery is None:
        return {"ok": True, "duplicate": True}

    article = payload.get("article")
    ticket = payload.get("ticket")
    outcome = "ignored_no_ticket"
    messages: list[str] = []
    sent_kinds: list[str] = []
    owner_message: str | None = None
    owner_link = None
    state_to_store: tuple[int, str, str, str] | None = None

    if isinstance(ticket, dict):
        ticket_id = nested_id(ticket.get("id"))
        number = str(ticket.get("number") or ticket_id or "?")
        zammad_customer_id = customer_id(ticket)
        link = find_active_zammad_link(db, zammad_customer_id) if zammad_customer_id else None
        zammad_owner_id = owner_id(ticket)
        owner_link = find_active_zammad_link(db, zammad_owner_id) if zammad_owner_id else None
        outcome = "ignored_no_article"

        current_state = ticket_state(ticket)
        if ticket_id is not None and current_state is not None:
            state_key, state_name = current_state
            snapshot = (
                db.query(TicketStateSnapshot)
                .where(TicketStateSnapshot.zammad_ticket_id == ticket_id)
                .first()
            )
            state_to_store = (ticket_id, number, state_key, state_name)
            if snapshot is None:
                # A status-only webhook is itself evidence of a state transition.
                # Article webhooks merely establish the initial state silently.
                if not isinstance(article, dict) and link is not None:
                    messages.append(
                        f"Заявка #{number}: статус змінено на «{localized_state_name(state_name)}»."
                    )
                    sent_kinds.append("state")
                else:
                    outcome = "state_baseline"
            elif snapshot.state_key != state_key:
                if link is None:
                    outcome = "ignored_unlinked_customer"
                else:
                    messages.append(
                        f"Заявка #{number}: статус змінено на «{localized_state_name(state_name)}»."
                    )
                    sent_kinds.append("state")

    if isinstance(article, dict) and isinstance(ticket, dict):
        if article.get("internal") is not False:
            if not sent_kinds:
                outcome = "ignored_internal"
        elif article_sender(article) == "customer":
            if owner_link is None:
                if not sent_kinds:
                    outcome = "ignored_unlinked_owner"
            else:
                body_text = html_to_text(str(article.get("body") or ""))
                if not body_text:
                    body_text = "Нове повідомлення без тексту."
                customer_name = str(article.get("origin_by") or "").strip() or sender_name(article)
                owner_message = (
                    f"Заявка #{number}: новий коментар від {customer_name}\n\n{body_text}"
                )
        elif article_sender(article) != "agent":
            if not sent_kinds:
                outcome = "ignored_non_agent"
        else:
            if link is None:
                if not sent_kinds:
                    outcome = "ignored_unlinked_customer"
            else:
                body_text = html_to_text(str(article.get("body") or ""))
                if not body_text:
                    body_text = "Нове повідомлення без тексту."
                agent_name = str(article.get("origin_by") or "").strip() or sender_name(article)
                messages.append(
                    f"Заявка #{number}: новий коментар від {agent_name}\n\n{body_text}"
                )
                sent_kinds.append("article")

    if messages and isinstance(ticket, dict) and link is not None:
        message = "\n\n——\n\n".join(messages)[:4096]
        try:
            await send_message(settings, link.telegram_chat_id, message)
        except httpx.HTTPError as exc:
            logger.exception("Telegram delivery failed for Zammad delivery=%s", x_zammad_delivery)
            db.delete(delivery)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Telegram delivery failed",
            ) from exc
        outcome = "sent_customer_" + "_".join(sent_kinds)

    if owner_message and owner_link is not None:
        try:
            await send_message(settings, owner_link.telegram_chat_id, owner_message[:4096])
        except httpx.HTTPError as exc:
            logger.exception("Telegram owner delivery failed for Zammad delivery=%s", x_zammad_delivery)
            db.delete(delivery)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Telegram owner delivery failed",
            ) from exc
        outcome = "sent_owner_article"

    if state_to_store is not None:
        stored_ticket_id, stored_number, state_key, state_name = state_to_store
        update_state_snapshot(
            db,
            ticket_id=stored_ticket_id,
            ticket_number=stored_number,
            state_key=state_key,
            state_name=state_name,
        )

    complete_delivery(db, delivery, outcome)
    return {"ok": True, "outcome": outcome, "duplicate": False}
