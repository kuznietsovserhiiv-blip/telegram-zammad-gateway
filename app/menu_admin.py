import argparse
import asyncio
import json

from app.config import get_settings
from app.i18n import SUPPORTED_LOCALES
from app.telegram_client import commands_for_mode, get_default_commands, set_commands


async def set_default() -> None:
    settings = get_settings()
    commands = {locale: commands_for_mode("default", locale) for locale in SUPPORTED_LOCALES}
    for locale, locale_commands in commands.items():
        await set_commands(settings, locale_commands, language_code=locale)
    print(json.dumps({"ok": True, "commands": commands}, ensure_ascii=False, indent=2))


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
