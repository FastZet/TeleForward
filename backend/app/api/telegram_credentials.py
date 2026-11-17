"""Superuser endpoints for Telegram API credential management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import DatabaseSession, get_current_superuser
from app.schemas.settings import (
    TelegramCredentialsStatusResponse,
    TelegramCredentialsUpdateRequest,
)
from app.services.telegram.credentials import TelegramCredentialsService

router = APIRouter(
    prefix="/api/v1/settings/telegram/credentials",
    tags=["Settings"],
    dependencies=[Depends(get_current_superuser)],
)


@router.get(
    "",
    response_model=TelegramCredentialsStatusResponse,
    summary="Get Telegram credential configuration status",
)
async def get_telegram_credentials_status(
    session: DatabaseSession,
) -> TelegramCredentialsStatusResponse:
    """Return presence flags only; credential values are never returned."""
    api_id_configured, api_hash_configured = await (
        TelegramCredentialsService(session).configuration_status()
    )
    return TelegramCredentialsStatusResponse(
        api_id_configured=api_id_configured,
        api_hash_configured=api_hash_configured,
    )


@router.put(
    "",
    response_model=TelegramCredentialsStatusResponse,
    summary="Set Telegram API credentials",
)
async def set_telegram_credentials(
    request: TelegramCredentialsUpdateRequest,
    session: DatabaseSession,
) -> TelegramCredentialsStatusResponse:
    """Encrypt and persist the API hash; never echo either credential."""
    service = TelegramCredentialsService(session)
    await service.set_credentials(
        request.api_id,
        request.api_hash.get_secret_value(),
    )
    await session.flush()
    return TelegramCredentialsStatusResponse(
        api_id_configured=True,
        api_hash_configured=True,
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear Telegram API credentials",
)
async def clear_telegram_credentials(
    session: DatabaseSession,
) -> Response:
    """Disable stored credentials without returning secret data."""
    await TelegramCredentialsService(session).clear_credentials()
    await session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

