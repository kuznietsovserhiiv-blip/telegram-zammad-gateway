import json
from pathlib import Path


SUPPORTED_LOCALES = ("uk", "en", "ru")
_LOCALES_DIR = Path(__file__).with_name("locales")


def _load_locale(locale: str) -> dict[str, str]:
    with (_LOCALES_DIR / f"{locale}.json").open(encoding="utf-8") as source:
        return json.load(source)


TEXT = {locale: _load_locale(locale) for locale in SUPPORTED_LOCALES}


def locale_from_telegram(language_code: object) -> str:
    """Return a supported Telegram UI locale, with Ukrainian as the fallback."""
    if isinstance(language_code, str):
        language = language_code.lower().split("-", 1)[0]
        if language in SUPPORTED_LOCALES:
            return language
    return "uk"


def text(locale: str, key: str) -> str:
    return TEXT.get(locale, TEXT["uk"])[key]
