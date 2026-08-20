import hashlib
import secrets

from fastapi import HTTPException, Request, status


def generate_link_token() -> str:
    # 256 bits of entropy; URL-safe and accepted by Telegram's start parameter.
    return secrets.token_urlsafe(32)


def hash_link_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    """Read a request body without buffering more than the configured limit."""
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        content_length = 0
    if content_length > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Webhook body is too large")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Webhook body is too large")
    return bytes(body)
