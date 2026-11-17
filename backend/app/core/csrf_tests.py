"""Tests for CSRF key loading from configured and generated settings."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core import csrf


@pytest.mark.parametrize(
    ("secret", "expected"),
    [
        (SecretStr("environment-secret"), b"environment-secret"),
        ("generated-secret", b"generated-secret"),
    ],
)
def test_get_signing_key_supports_secretstr_and_persisted_values(
    secret: SecretStr | str,
    expected: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        csrf,
        "get_settings",
        lambda: SimpleNamespace(secret_key=secret),
    )

    assert csrf._get_signing_key() == expected

