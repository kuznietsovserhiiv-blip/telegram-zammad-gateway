import asyncio

from app.config import Settings
from app.zammad import ZammadApi


def test_article_attachment_is_base64_encoded() -> None:
    api = ZammadApi(Settings())
    captured: dict[str, object] = {}

    async def fake_request(method: str, path: str, **kwargs: object) -> dict[str, int]:
        captured.update({"method": method, "path": path, **kwargs})
        return {"id": 1}

    api.request = fake_request  # type: ignore[method-assign]
    asyncio.run(
        api.add_article(
            ticket_id=12,
            user_id=34,
            body="Voice message",
            sender="Customer",
            article_type="web",
            attachments=[("telegram-voice.ogg", "audio/ogg", b"audio")],
        )
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/ticket_articles"
    assert captured["json"] == {
        "ticket_id": 12,
        "body": "Voice message",
        "content_type": "text/plain",
        "type": "web",
        "internal": False,
        "sender": "Customer",
        "origin_by_id": 34,
        "attachments": [
            {"filename": "telegram-voice.ogg", "mime-type": "audio/ogg", "data": "YXVkaW8="}
        ],
    }
