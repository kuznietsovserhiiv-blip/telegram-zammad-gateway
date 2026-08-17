from app.config import Settings
from app.telegram import (
    command_name,
    format_ticket_list,
    ticket_inline_keyboard,
    ticket_title,
    user_mode,
    customer_can_access_ticket,
    zammad_search_value,
)
from app.telegram_client import commands_for_mode, keyboard_for_mode


def settings() -> Settings:
    return Settings(
        zammad_admin_role_id=1,
        zammad_agent_role_id=2,
        zammad_customer_role_id=3,
    )


def test_admin_has_precedence_over_agent() -> None:
    assert user_mode({"role_ids": [1, 2]}, settings()) == "admin"


def test_customer_mode() -> None:
    assert user_mode({"role_ids": [3]}, settings()) == "customer"


def test_agent_only_is_disabled() -> None:
    assert user_mode({"role_ids": [2]}, settings()) == "agent_disabled"


def test_inactive_user_is_denied() -> None:
    assert user_mode({"active": False, "role_ids": [1]}, settings()) == "denied"


def test_customer_ticket_access_requires_owner_and_open_state() -> None:
    assert customer_can_access_ticket({"customer_id": 42, "state": "open"}, 42)
    assert customer_can_access_ticket(
        {"customer": {"id": 42}, "state": {"name": "open"}}, 42
    )
    assert not customer_can_access_ticket({"customer_id": 43, "state": "open"}, 42)
    assert not customer_can_access_ticket({"customer_id": 42, "state": {"name": "closed"}}, 42)


def test_command_parsing() -> None:
    assert command_name("/new Printer is offline") == ("/new", "Printer is offline")
    assert command_name("📝 Нова заявка") == ("/new", "")
    assert command_name("📋 Мої незакриті заявки") == ("/mytickets", "")
    assert command_name("📋 Мої заявки") == ("/my", "")


def test_ticket_title_uses_first_nonempty_line() -> None:
    assert ticket_title("\n Printer is offline\nMore details") == "Printer is offline"


def test_role_specific_bot_commands() -> None:
    assert [item["command"] for item in commands_for_mode("customer")] == [
        "new",
        "mytickets",
        "current",
        "close",
        "help",
    ]
    assert [item["command"] for item in commands_for_mode("admin")] == [
        "my",
        "newtickets",
        "ticket",
        "current",
        "close",
        "help",
    ]
    assert [item["command"] for item in commands_for_mode("denied")] == [
        "start",
        "help",
    ]
    assert keyboard_for_mode("customer")["is_persistent"] is True
    assert keyboard_for_mode("admin")["is_persistent"] is True
    assert keyboard_for_mode("denied") is None


def test_ticket_list_format() -> None:
    text = format_ticket_list(
        "Мої активні заявки:",
        [
            {
                "number": "811026",
                "title": "Printer is offline",
                "state": "open",
                "group": "SKYWELL",
                "owner": "admin@example.com",
            }
        ],
    )
    assert "#811026 · open · SKYWELL" in text
    assert "Printer is offline" in text
    assert "/ticket <номер>" in text

    customer_text = format_ticket_list(
        "Мої незакриті заявки:",
        [{"number": "811026", "title": "Printer is offline"}],
        footer=None,
    )
    assert "#811026" in customer_text
    assert "/ticket" not in customer_text


def test_ticket_inline_keyboard() -> None:
    keyboard = ticket_inline_keyboard(
        [
            {
                "id": 1026,
                "number": "811026",
                "title": "Printer is offline",
                "state": "open",
            }
        ]
    )
    button = keyboard["inline_keyboard"][0][0]
    assert button["callback_data"] == "select_ticket:1026"
    assert "#811026 · open · Printer is offline" == button["text"]


def test_zammad_search_value_escapes_query_syntax() -> None:
    assert zammad_search_value('a"b\\c') == 'a\\"b\\\\c'
