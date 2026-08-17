SUPPORTED_LOCALES = ("uk", "ru")


TEXT = {
    "uk": {
        "start": "Почати роботу", "help": "Показати доступні команди",
        "new": "Створити нову заявку", "mytickets": "Мої незакриті заявки",
        "current": "Показати поточну заявку", "close": "Завершити поточний діалог",
        "my": "Мої активні заявки", "newtickets": "Усі нові заявки",
        "ticket": "Вибрати заявку за номером",
        "button_new": "📝 Нова заявка", "button_mytickets": "📋 Мої незакриті заявки",
        "button_current": "📌 Поточна заявка", "button_close": "✅ Завершити діалог",
        "button_help": "ℹ️ Допомога", "button_my": "📋 Мої заявки",
        "button_newtickets": "🆕 Нові заявки", "button_ticket": "🔎 Вибрати заявку",
        "new_placeholder": "Опишіть проблему", "ticket_placeholder": "Введіть номер заявки",
    },
    "ru": {
        "start": "Начать работу", "help": "Показать доступные команды",
        "new": "Создать новую заявку", "mytickets": "Мои незакрытые заявки",
        "current": "Показать текущую заявку", "close": "Завершить текущий диалог",
        "my": "Мои активные заявки", "newtickets": "Все новые заявки",
        "ticket": "Выбрать заявку по номеру",
        "button_new": "📝 Новая заявка", "button_mytickets": "📋 Мои незакрытые заявки",
        "button_current": "📌 Текущая заявка", "button_close": "✅ Завершить диалог",
        "button_help": "ℹ️ Помощь", "button_my": "📋 Мои заявки",
        "button_newtickets": "🆕 Новые заявки", "button_ticket": "🔎 Выбрать заявку",
        "new_placeholder": "Опишите проблему", "ticket_placeholder": "Введите номер заявки",
    },
}


def locale_from_telegram(language_code: object) -> str:
    """Use Russian only when Telegram explicitly reports a Russian locale."""
    if isinstance(language_code, str) and language_code.lower().startswith("ru"):
        return "ru"
    return "uk"


def text(locale: str, key: str) -> str:
    return TEXT.get(locale, TEXT["uk"])[key]
