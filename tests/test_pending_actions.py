from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.session_service import clear_pending_action, get_pending_action, set_pending_action


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_pending_action_round_trip() -> None:
    db = make_db()
    row = set_pending_action(db, telegram_user_id=777, action="customer_new", now=1000)
    assert row.action == "customer_new"
    assert get_pending_action(db, 777, now=1001) is not None
    assert clear_pending_action(db, 777) is True
    assert get_pending_action(db, 777, now=1002) is None


def test_pending_action_expires() -> None:
    db = make_db()
    set_pending_action(db, telegram_user_id=777, action="admin_ticket", now=1000)
    assert get_pending_action(db, 777, now=2000) is None
