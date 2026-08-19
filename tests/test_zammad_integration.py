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
        'a=App.Config.get("auth_provider_all"),n=[];for(o in a)'
        'i=a[o],(!0===this.Config.get(i.config)||"true"===this.Config.get(i.config))'
        '&&n.push(i)'
    )
    patched = patch_bundle_text(source)
    assert TELEGRAM_PROVIDER in patched
    assert f"i.{LOGIN_FILTER}&&n.push(i)" in patched
    assert patch_bundle_text(patched) == patched


def test_patch_upgrades_legacy_login_provider() -> None:
    source = (
        f'{LEGACY_TELEGRAM_PROVIDER};'
        'a=App.Config.get("auth_provider_all"),n=[];for(o in a)'
        'i=a[o],(!0===this.Config.get(i.config)||"true"===this.Config.get(i.config))'
        '&&n.push(i)'
    )
    patched = patch_bundle_text(source)
    assert TELEGRAM_PROVIDER in patched
    assert LEGACY_TELEGRAM_PROVIDER not in patched


def test_patch_rejects_unknown_bundle() -> None:
    with pytest.raises(IntegrationError, match="provider anchor"):
        patch_bundle_text("unknown bundle")
