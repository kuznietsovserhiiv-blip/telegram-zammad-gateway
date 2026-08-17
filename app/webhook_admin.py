import json
import sys
import urllib.parse
import urllib.request

from app.config import get_settings


def call(method: str, payload: dict | None = None) -> dict:
    settings = get_settings()
    if settings.telegram_bot_token in {"", "replace_me"}:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not configured")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    data = urllib.parse.urlencode(payload or {}).encode()
    with urllib.request.urlopen(url, data=data, timeout=15) as response:
        return json.load(response)


def main() -> None:
    settings = get_settings()
    command = sys.argv[1] if len(sys.argv) > 1 else "info"
    if command == "set":
        if settings.telegram_webhook_secret in {"", "replace_me"}:
            raise SystemExit("TELEGRAM_WEBHOOK_SECRET is not configured")
        result = call(
            "setWebhook",
            {
                "url": f"{settings.public_base_url}/telegram/webhook",
                "secret_token": settings.telegram_webhook_secret,
                "allowed_updates": json.dumps(["message", "callback_query"]),
                "drop_pending_updates": "false",
            },
        )
    elif command == "delete":
        result = call("deleteWebhook", {"drop_pending_updates": "false"})
    elif command == "info":
        result = call("getWebhookInfo")
    else:
        raise SystemExit("Usage: python -m app.webhook_admin [set|info|delete]")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
