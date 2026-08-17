import pytest

from zammad_integration.linked_accounts import (
    MARKER,
    PROVIDER_ANCHOR,
    TELEGRAM_PROVIDER,
    IntegrationError,
    patch_bundle_text,
)


def test_patch_adds_telegram_provider_once() -> None:
    source = f"before,{PROVIDER_ANCHOR},after"
    patched = patch_bundle_text(source)
    assert TELEGRAM_PROVIDER in patched
    assert patched.count(MARKER) == 1
    assert patch_bundle_text(patched) == patched


def test_patch_rejects_unknown_bundle() -> None:
    with pytest.raises(IntegrationError, match="provider anchor"):
        patch_bundle_text("unknown bundle")
