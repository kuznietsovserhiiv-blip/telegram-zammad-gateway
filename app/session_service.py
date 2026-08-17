import time

from sqlalchemy.orm import Session

from app.models import ChatSession, PendingAction, TelegramTicket


PENDING_ACTION_TTL_SECONDS = 15 * 60


def get_chat_session(db: Session, telegram_user_id: int) -> ChatSession | None:
    return db.query(ChatSession).where(ChatSession.telegram_user_id == telegram_user_id).first()


def set_chat_session(
    db: Session,
    *,
    telegram_user_id: int,
    mode: str,
    zammad_ticket_id: int,
    ticket_number: str,
    ticket_title: str,
    now: int | None = None,
) -> ChatSession:
    now = now or int(time.time())
    row = get_chat_session(db, telegram_user_id)
    if row is None:
        row = ChatSession(
            telegram_user_id=telegram_user_id,
            mode=mode,
            zammad_ticket_id=zammad_ticket_id,
            ticket_number=ticket_number,
            ticket_title=ticket_title,
            updated_at=now,
        )
        db.add(row)
    else:
        row.mode = mode
        row.zammad_ticket_id = zammad_ticket_id
        row.ticket_number = ticket_number
        row.ticket_title = ticket_title
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def clear_chat_session(db: Session, telegram_user_id: int) -> bool:
    row = get_chat_session(db, telegram_user_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def get_pending_action(
    db: Session,
    telegram_user_id: int,
    *,
    now: int | None = None,
) -> PendingAction | None:
    now = now or int(time.time())
    row = db.query(PendingAction).where(PendingAction.telegram_user_id == telegram_user_id).first()
    if row is not None and row.updated_at < now - PENDING_ACTION_TTL_SECONDS:
        db.delete(row)
        db.commit()
        return None
    return row


def set_pending_action(
    db: Session,
    *,
    telegram_user_id: int,
    action: str,
    now: int | None = None,
) -> PendingAction:
    now = now or int(time.time())
    row = get_pending_action(db, telegram_user_id, now=now)
    if row is None:
        row = PendingAction(
            telegram_user_id=telegram_user_id,
            action=action,
            updated_at=now,
        )
        db.add(row)
    else:
        row.action = action
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def clear_pending_action(db: Session, telegram_user_id: int) -> bool:
    row = db.query(PendingAction).where(PendingAction.telegram_user_id == telegram_user_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def remember_telegram_ticket(
    db: Session,
    *,
    zammad_ticket_id: int,
    ticket_number: str,
    telegram_user_id: int,
    telegram_chat_id: int,
    zammad_customer_id: int,
    group_id: int,
    now: int | None = None,
) -> TelegramTicket:
    now = now or int(time.time())
    row = TelegramTicket(
        zammad_ticket_id=zammad_ticket_id,
        ticket_number=ticket_number,
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        zammad_customer_id=zammad_customer_id,
        group_id=group_id,
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
