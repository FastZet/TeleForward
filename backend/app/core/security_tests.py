"""Regression tests for secrets loaded from settings and lifecycle state."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core import security


@pytest.mark.parametrize(
    "configured_secret",
    [SecretStr("configured-secret"), "persisted-secret"],
)
def test_configured_secret_accepts_secretstr_and_lifecycle_string(
    configured_secret: SecretStr | str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(jwt_secret_key=configured_secret),
    )

    assert security._get_configured_secret("jwt_secret_key") in {
        "configured-secret",
        "persisted-secret",
    }


def test_configured_secret_rejects_unexpected_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(jwt_secret_key=object()),
    )

    with pytest.raises(RuntimeError, match="must be configured as a string"):
        security._get_configured_secret("jwt_secret_key")

