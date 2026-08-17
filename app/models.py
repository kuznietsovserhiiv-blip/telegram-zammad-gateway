from sqlalchemy import BigInteger, Boolean, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LinkToken(Base):
    __tablename__ = "link_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    zammad_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    zammad_login: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_link_tokens_user_active", "zammad_user_id", "used_at", "revoked"),)


class TelegramLink(Base):
    __tablename__ = "telegram_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zammad_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    zammad_login: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("telegram_user_id", name="uq_telegram_links_telegram_user"),
        UniqueConstraint("zammad_user_id", name="uq_telegram_links_zammad_user"),
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    zammad_ticket_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ticket_number: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_title: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TelegramTicket(Base):
    __tablename__ = "telegram_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zammad_ticket_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    ticket_number: Mapped[str] = mapped_column(String(64), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    zammad_customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ZammadWebhookDelivery(Base):
    __tablename__ = "zammad_webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    received_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TicketStateSnapshot(Base):
    __tablename__ = "ticket_state_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zammad_ticket_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    ticket_number: Mapped[str] = mapped_column(String(64), nullable=False)
    state_key: Mapped[str] = mapped_column(String(255), nullable=False)
    state_name: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
