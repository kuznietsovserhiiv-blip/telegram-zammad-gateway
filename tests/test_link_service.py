from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.link_service import LinkConflictError, bind_telegram_user, consume_link_token, issue_link_token
from app.models import LinkToken, TelegramLink, TelegramUpdate
from app.telegram import reserve_telegram_update


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_token_is_one_time() -> None:
    db = make_db()
    issued = issue_link_token(db, zammad_user_id=42, zammad_login="user@example.com", ttl_seconds=600, now=1000)
    assert consume_link_token(db, token=issued.token, now=1001) is not None
    db.commit()
    assert consume_link_token(db, token=issued.token, now=1002) is None


def test_token_expires() -> None:
    db = make_db()
    issued = issue_link_token(db, zammad_user_id=42, zammad_login="user@example.com", ttl_seconds=600, now=1000)
    assert consume_link_token(db, token=issued.token, now=1601) is None


def test_new_token_revokes_previous_token() -> None:
    db = make_db()
    first = issue_link_token(db, zammad_user_id=42, zammad_login="user@example.com", ttl_seconds=600, now=1000)
    second = issue_link_token(db, zammad_user_id=42, zammad_login="user@example.com", ttl_seconds=600, now=1001)
    assert consume_link_token(db, token=first.token, now=1002) is None
    assert consume_link_token(db, token=second.token, now=1002) is not None
    assert db.query(LinkToken).count() == 2


def test_token_binds_telegram_to_zammad() -> None:
    db = make_db()
    issued = issue_link_token(db, zammad_user_id=42, zammad_login="user@example.com", ttl_seconds=600, now=1000)
    token_row = consume_link_token(db, token=issued.token, now=1001)
    assert token_row is not None
    link = bind_telegram_user(
        db,
        link_token=token_row,
        telegram_user_id=777,
        telegram_chat_id=777,
        telegram_username="testuser",
        now=1001,
    )
    db.commit()
    assert link.zammad_user_id == 42
    assert db.query(TelegramLink).one().telegram_user_id == 777


def test_link_conflict_rolls_back() -> None:
    db = make_db()
    first = issue_link_token(db, zammad_user_id=42, zammad_login="first@example.com", ttl_seconds=600, now=1000)
    first_row = consume_link_token(db, token=first.token, now=1001)
    assert first_row is not None
    bind_telegram_user(db, link_token=first_row, telegram_user_id=777, telegram_chat_id=777, telegram_username=None, now=1001)
    db.commit()

    second = issue_link_token(db, zammad_user_id=43, zammad_login="second@example.com", ttl_seconds=600, now=1002)
    second_row = consume_link_token(db, token=second.token, now=1003)
    assert second_row is not None
    try:
        bind_telegram_user(db, link_token=second_row, telegram_user_id=777, telegram_chat_id=777, telegram_username=None, now=1003)
        assert False, "expected conflict"
    except LinkConflictError:
        db.rollback()
    assert db.query(TelegramLink).count() == 1


def test_telegram_update_is_reserved_once() -> None:
    db = make_db()
    assert reserve_telegram_update(db, 12345) is True
    assert reserve_telegram_update(db, 12345) is False
    assert db.query(TelegramUpdate).count() == 1
