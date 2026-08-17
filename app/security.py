import hashlib
import secrets


def generate_link_token() -> str:
    # 256 bits of entropy; URL-safe and accepted by Telegram's start parameter.
    return secrets.token_urlsafe(32)


def hash_link_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

