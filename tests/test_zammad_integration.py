import pytest

from zammad_integration.linked_accounts import (
    LEGACY_TELEGRAM_PROVIDER,
    LOGIN_PUSH,
    LOGIN_PUSH_PATCHED,
    PROVIDER_ANCHOR,
    TELEGRAM_PROVIDER,
    IntegrationError,
    patch_bundle_text,
)


def test_patch_keeps_telegram_only_in_linked_accounts() -> None:
    patched = patch_bundle_text(f"{PROVIDER_ANCHOR};{LOGIN_PUSH}")
    assert TELEGRAM_PROVIDER in patched
    assert LOGIN_PUSH_PATCHED in patched
    assert patch_bundle_text(patched) == patched


def test_patch_upgrades_legacy_login_provider() -> None:
    patched = patch_bundle_text(f"{LEGACY_TELEGRAM_PROVIDER};{LOGIN_PUSH}")
    assert TELEGRAM_PROVIDER in patched
    assert LEGACY_TELEGRAM_PROVIDER not in patched


def test_patch_rejects_unknown_bundle() -> None:
    with pytest.raises(IntegrationError, match="provider anchor"):
        patch_bundle_text("unknown bundle")
