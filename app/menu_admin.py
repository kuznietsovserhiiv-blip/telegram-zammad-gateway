import argparse
import asyncio
import json

from app.config import get_settings
from app.telegram_client import DEFAULT_COMMANDS, get_default_commands, set_commands


async def set_default() -> None:
    settings = get_settings()
    await set_commands(settings, DEFAULT_COMMANDS)
    print(json.dumps({"ok": True, "commands": DEFAULT_COMMANDS}, ensure_ascii=False, indent=2))


async def info_default() -> None:
    settings = get_settings()
    commands = await get_default_commands(settings)
    print(json.dumps({"ok": True, "commands": commands}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Telegram bot command menu")
    parser.add_argument("action", choices=("set-default", "info-default"))
    args = parser.parse_args()
    asyncio.run({"set-default": set_default, "info-default": info_default}[args.action]())


if __name__ == "__main__":
    main()
