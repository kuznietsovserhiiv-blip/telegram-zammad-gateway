from collections.abc import Generator
import time

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models import LinkToken, TelegramUpdate, ZammadWebhookDelivery

    Base.metadata.create_all(bind=engine)
    cutoff = int(time.time()) - max(1, settings.event_retention_days) * 86400
    now = int(time.time())
    with SessionLocal.begin() as db:
        db.execute(delete(TelegramUpdate).where(TelegramUpdate.received_at < cutoff))
        db.execute(
            delete(ZammadWebhookDelivery).where(
                ZammadWebhookDelivery.received_at < cutoff,
                ZammadWebhookDelivery.outcome != "processing",
            )
        )
        db.execute(
            delete(LinkToken).where(
                LinkToken.expires_at < now,
            )
        )
