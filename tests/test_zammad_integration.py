import pytest

from zammad_integration.linked_accounts import (
    LEGACY_TELEGRAM_PROVIDER,
    LOGIN_FILTER,
    PROVIDER_ANCHOR,
    TELEGRAM_PROVIDER,
    IntegrationError,
    patch_bundle_text,
)


def test_patch_keeps_telegram_only_in_linked_accounts() -> None:
    source = (
        f'{PROVIDER_ANCHOR};'
        'n=[],e=App.Config.get("auth_provider_all"))s=e[i],'
        '!0!==this.Config.get(s.config)&&"true"!==this.Config.get(s.config)||n.push(s)'
    )
    patched = patch_bundle_text(source)
    assert TELEGRAM_PROVIDER in patched
    assert f"s.{LOGIN_FILTER}&&n.push(s)" in patched
    assert patch_bundle_text(patched) == patched


def test_patch_upgrades_legacy_login_provider() -> None:
    source = (
        f'{LEGACY_TELEGRAM_PROVIDER};'
        'n=[],e=App.Config.get("auth_provider_all"))s=e[i],'
        '!0!==this.Config.get(s.config)&&"true"!==this.Config.get(s.config)||n.push(s)'
    )
    patched = patch_bundle_text(source)
    assert TELEGRAM_PROVIDER in patched
    assert LEGACY_TELEGRAM_PROVIDER not in patched


def test_patch_rejects_unknown_bundle() -> None:
    with pytest.raises(IntegrationError, match="provider anchor"):
        patch_bundle_text("unknown bundle")
