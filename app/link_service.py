import time
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import LinkToken, TelegramLink
from app.security import generate_link_token, hash_link_token


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: int


def issue_link_token(
    db: Session,
    *,
    zammad_user_id: int,
    zammad_login: str,
    ttl_seconds: int,
    now: int | None = None,
) -> IssuedToken:
    now = now or int(time.time())
    token = generate_link_token()
    expires_at = now + ttl_seconds

    # Only the newest unused token for a Zammad user remains valid.
    db.execute(
        update(LinkToken)
        .where(
            LinkToken.zammad_user_id == zammad_user_id,
            LinkToken.used_at.is_(None),
            LinkToken.revoked.is_(False),
        )
        .values(revoked=True)
    )
    db.add(
        LinkToken(
            token_hash=hash_link_token(token),
            zammad_user_id=zammad_user_id,
            zammad_login=zammad_login,
            created_at=now,
            expires_at=expires_at,
            revoked=False,
        )
    )
    db.commit()
    return IssuedToken(token=token, expires_at=expires_at)


def consume_link_token(db: Session, *, token: str, now: int | None = None) -> LinkToken | None:
    """Atomically reserve a valid token in the caller's transaction."""
    now = now or int(time.time())
    token_hash = hash_link_token(token)
    token_id = db.execute(
        update(LinkToken)
        .where(
            LinkToken.token_hash == token_hash,
            LinkToken.used_at.is_(None),
            LinkToken.revoked.is_(False),
            LinkToken.expires_at >= now,
        )
        .values(used_at=now)
        .returning(LinkToken.id)
    ).scalar_one_or_none()
    if token_id is None:
        return None
    return db.get(LinkToken, token_id)


class LinkConflictError(RuntimeError):
    pass


def bind_telegram_user(
    db: Session,
    *,
    link_token: LinkToken,
    telegram_user_id: int,
    telegram_chat_id: int,
    telegram_username: str | None,
    now: int | None = None,
) -> TelegramLink:
    now = now or int(time.time())
    by_telegram = db.query(TelegramLink).where(TelegramLink.telegram_user_id == telegram_user_id).first()
    by_zammad = db.query(TelegramLink).where(TelegramLink.zammad_user_id == link_token.zammad_user_id).first()

    if by_telegram and by_telegram.zammad_user_id != link_token.zammad_user_id:
        raise LinkConflictError("Цей Telegram вже прив’язаний до іншого профілю Zammad.")
    if by_zammad and by_zammad.telegram_user_id != telegram_user_id:
        raise LinkConflictError("Цей профіль Zammad вже прив’язаний до іншого Telegram.")

    link = by_telegram or by_zammad
    if link is None:
        link = TelegramLink(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_username=telegram_username,
            zammad_user_id=link_token.zammad_user_id,
            zammad_login=link_token.zammad_login,
            created_at=now,
            updated_at=now,
            active=True,
        )
        db.add(link)
    else:
        link.telegram_chat_id = telegram_chat_id
        link.telegram_username = telegram_username
        link.zammad_login = link_token.zammad_login
        link.updated_at = now
        link.active = True
    return link


def find_active_telegram_link(db: Session, telegram_user_id: int) -> TelegramLink | None:
    return (
        db.query(TelegramLink)
        .where(TelegramLink.telegram_user_id == telegram_user_id, TelegramLink.active.is_(True))
        .first()
    )


def find_active_zammad_link(db: Session, zammad_user_id: int) -> TelegramLink | None:
    return (
        db.query(TelegramLink)
        .where(TelegramLink.zammad_user_id == zammad_user_id, TelegramLink.active.is_(True))
        .first()
    )
