import asyncio
import hashlib
import hmac
import json

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base
from app.link_service import find_active_zammad_link
from app.models import TelegramLink, TicketStateSnapshot
from app.zammad_webhook import (
    article_sender,
    customer_id,
    html_to_text,
    localized_state_name,
    owner_id,
    reserve_delivery,
    ticket_state,
    valid_signature,
    zammad_webhook,
)


def make_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def make_request(body: bytes) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/zammad/webhook", "headers": []}, receive)


def test_zammad_signature_accepts_prefixed_sha1() -> None:
    body = b'{"ticket":{"id":1}}'
    secret = "test-secret"
    digest = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    assert valid_signature(body, f"sha1={digest}", secret)
    assert not valid_signature(body + b" ", f"sha1={digest}", secret)


def test_html_article_becomes_plain_text() -> None:
    assert html_to_text("Hello&nbsp;<b>world</b><div><br></div>Next") == "Hello world\nNext"


def test_payload_helpers_support_objects_and_ids() -> None:
    assert article_sender({"sender": {"name": "Agent"}}) == "agent"
    assert customer_id({"customer": {"id": 42}}) == 42
    assert customer_id({"customer_id": 43}) == 43
    assert owner_id({"owner": {"id": 44}}) == 44
    assert owner_id({"owner_id": 45}) == 45
    assert ticket_state({"state_id": 4, "state": {"id": 4, "name": "closed"}}) == (
        "id:4",
        "closed",
    )
    assert localized_state_name("closed") == "закрита"


def test_find_link_by_zammad_user() -> None:
    db = make_db()
    db.add(
        TelegramLink(
            telegram_user_id=777,
            telegram_chat_id=888,
            telegram_username="user",
            zammad_user_id=42,
            zammad_login="user@example.com",
            created_at=1,
            updated_at=1,
            active=True,
        )
    )
    db.commit()
    assert find_active_zammad_link(db, 42).telegram_chat_id == 888


def test_delivery_id_is_reserved_once() -> None:
    db = make_db()
    assert reserve_delivery(db, "delivery-1") is not None
    assert reserve_delivery(db, "delivery-1") is None


def test_stale_processing_delivery_can_be_retried() -> None:
    db = make_db()
    assert reserve_delivery(db, "delivery-stale", now=1000) is not None
    assert reserve_delivery(db, "delivery-stale", now=1301) is not None


def test_public_agent_article_is_sent_once(monkeypatch) -> None:
    db = make_db()
    db.add(
        TelegramLink(
            telegram_user_id=777,
            telegram_chat_id=888,
            telegram_username="user",
            zammad_user_id=42,
            zammad_login="user@example.com",
            created_at=1,
            updated_at=1,
            active=True,
        )
    )
    db.commit()
    sent: list[tuple[int, str]] = []

    async def fake_send_message(settings: Settings, chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    secret = "test-secret"
    settings = Settings(zammad_webhook_secret=secret, zammad_service_user_id=260)
    monkeypatch.setattr("app.zammad_webhook.send_message", fake_send_message)
    payload = {
        "ticket": {
            "id": 100,
            "number": "811026",
            "customer_id": 42,
            "state_id": 2,
            "state": {"id": 2, "name": "open"},
        },
        "article": {
            "id": 4759,
            "body": "Public <b>reply</b>",
            "internal": False,
            "sender": "Agent",
            "created_by_id": 260,
            "created_by": {"id": 260, "firstname": "Telegram", "lastname": "Gateway"},
            "origin_by": "Serhii Kuznetsov",
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    first = asyncio.run(
        zammad_webhook(
            make_request(body),
            x_hub_signature=f"sha1={signature}",
            x_zammad_delivery="delivery-integration-1",
            db=db,
            settings=settings,
        )
    )
    second = asyncio.run(
        zammad_webhook(
            make_request(body),
            x_hub_signature=f"sha1={signature}",
            x_zammad_delivery="delivery-integration-1",
            db=db,
            settings=settings,
        )
    )

    assert first["outcome"] == "sent_customer_article"
    assert second["duplicate"] is True
    assert sent == [(888, "Заявка #811026: новий коментар від Serhii Kuznetsov\n\nPublic reply")]
    snapshot = db.query(TicketStateSnapshot).one()
    assert snapshot.state_key == "id:2"


def test_public_customer_article_is_sent_to_linked_ticket_owner(monkeypatch) -> None:
    db = make_db()
    db.add(
        TelegramLink(
            telegram_user_id=999,
            telegram_chat_id=1000,
            telegram_username="admin",
            zammad_user_id=7,
            zammad_login="admin@example.com",
            created_at=1,
            updated_at=1,
            active=True,
        )
    )
    db.commit()
    sent: list[tuple[int, str]] = []

    async def fake_send_message(settings: Settings, chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    secret = "test-secret"
    settings = Settings(zammad_webhook_secret=secret, zammad_service_user_id=260)
    monkeypatch.setattr("app.zammad_webhook.send_message", fake_send_message)
    payload = {
        "ticket": {"id": 100, "number": "811026", "customer_id": 42, "owner_id": 7},
        "article": {
            "id": 4760,
            "body": "Need <b>help</b>",
            "internal": False,
            "sender": "Customer",
            "created_by_id": 260,
            "created_by": {"id": 260, "firstname": "Telegram", "lastname": "Gateway"},
            "origin_by": "Iryna Customer",
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    response = asyncio.run(
        zammad_webhook(
            make_request(body),
            x_hub_signature=f"sha1={signature}",
            x_zammad_delivery="delivery-owner-article-1",
            db=db,
            settings=settings,
        )
    )

    assert response["outcome"] == "sent_owner_article"
    assert sent == [(1000, "Заявка #811026: новий коментар від Iryna Customer\n\nNeed help")]


def test_state_change_is_sent_after_baseline(monkeypatch) -> None:
    db = make_db()
    db.add_all(
        [
            TelegramLink(
                telegram_user_id=777,
                telegram_chat_id=888,
                telegram_username="user",
                zammad_user_id=42,
                zammad_login="user@example.com",
                created_at=1,
                updated_at=1,
                active=True,
            ),
            TicketStateSnapshot(
                zammad_ticket_id=100,
                ticket_number="811026",
                state_key="id:2",
                state_name="open",
                updated_at=1,
            ),
        ]
    )
    db.commit()
    sent: list[tuple[int, str]] = []

    async def fake_send_message(settings: Settings, chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    secret = "test-secret"
    settings = Settings(zammad_webhook_secret=secret, zammad_service_user_id=260)
    monkeypatch.setattr("app.zammad_webhook.send_message", fake_send_message)
    payload = {
        "ticket": {
            "id": 100,
            "number": "811026",
            "customer_id": 42,
            "state_id": 4,
            "state": {"id": 4, "name": "closed"},
        }
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    response = asyncio.run(
        zammad_webhook(
            make_request(body),
            x_hub_signature=f"sha1={signature}",
            x_zammad_delivery="delivery-state-1",
            db=db,
            settings=settings,
        )
    )

    assert response["outcome"] == "sent_customer_state"
    assert sent == [(888, "Заявка #811026: статус змінено на «закрита».")]
    assert db.query(TicketStateSnapshot).one().state_key == "id:4"
