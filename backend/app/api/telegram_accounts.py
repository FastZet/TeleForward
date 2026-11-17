"""Superuser endpoints for Telegram account and session setup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from telethon.errors import SessionPasswordNeededError

from app.core.dependencies import DatabaseSession, get_current_superuser
from app.core.rate_limiter import limiter
from app.core.security import encrypt_value
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.schemas.telegram_account import (
    TelegramAccountCreateRequest,
    TelegramAccountListResponse,
    TelegramAccountResponse,
    TelegramAccountStatusSchema,
)
from app.schemas.telegram_session import (
    TelegramChallengeTypeSchema,
    TelegramSessionChallengeResponse,
    TelegramSessionCodeRequest,
    TelegramSessionOperationResponse,
    TelegramSessionPasswordRequest,
    TelegramSessionStartRequest,
    TelegramSessionStatusSchema,
)
from app.services.telegram.account import TelegramAccountService
from app.services.telegram.credentials import TelegramCredentialsService


router = APIRouter(
    prefix="/api/v1/telegram",
    tags=["Telegram Accounts"],
    dependencies=[Depends(get_current_superuser)],
)


def _account_status(status_value: TelegramAccountStatus) -> TelegramAccountStatusSchema:
    return {
        TelegramAccountStatus.PENDING: TelegramAccountStatusSchema.DISCONNECTED,
        TelegramAccountStatus.DISCONNECTED: TelegramAccountStatusSchema.DISCONNECTED,
        TelegramAccountStatus.CONNECTING: TelegramAccountStatusSchema.CONNECTING,
        TelegramAccountStatus.CONNECTED: TelegramAccountStatusSchema.CONNECTED,
        TelegramAccountStatus.REQUIRES_AUTH: TelegramAccountStatusSchema.EXPIRED,
        TelegramAccountStatus.REQUIRES_2FA: TelegramAccountStatusSchema.AWAITING_PASSWORD,
        TelegramAccountStatus.ERROR: TelegramAccountStatusSchema.ERROR,
        TelegramAccountStatus.DISABLED: TelegramAccountStatusSchema.DISCONNECTED,
    }[status_value]


def _account_response(account: TelegramAccount) -> TelegramAccountResponse:
    return TelegramAccountResponse(
        id=account.id,
        phone_number=account.phone_number,
        display_name=account.name,
        telegram_user_id=account.telegram_user_id,
        telegram_username=account.telegram_username,
        first_name=account.first_name,
        last_name=account.last_name,
        status=_account_status(account.status),
        enabled=account.is_enabled,
        connected_at=account.last_connected_at,
        last_active_at=account.last_authenticated_at,
        last_error=account.last_error,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


async def _api_credentials(session):
    credentials = await TelegramCredentialsService(session).get_credentials()
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telegram API credentials have not been configured.",
        )
    return credentials


async def _save_authenticated_session(
    request: Request,
    session,
    account_id: int,
    result,
) -> None:
    manager = getattr(request.app.state, "telegram_client_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram session management is unavailable.",
        )
    session_string = await manager.export_session(account_id)
    if not session_string:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The authenticated Telegram session could not be persisted.",
        )
    service = TelegramAccountService(session)
    await service.update_identity(
        account_id,
        telegram_user_id=result.telegram_user_id,
        username=result.username,
    )
    await service.store_encrypted_session(
        account_id,
        encrypt_value(session_string),
    )
    await service.update_status(account_id, TelegramAccountStatus.CONNECTED)


@router.get("/accounts", response_model=TelegramAccountListResponse)
async def list_telegram_accounts(
    session: DatabaseSession,
) -> TelegramAccountListResponse:
    accounts = await TelegramAccountService(session).list_accounts()
    return TelegramAccountListResponse(
        accounts=[_account_response(account) for account in accounts],
        total=len(accounts),
    )


@router.post(
    "/accounts",
    response_model=TelegramAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_telegram_account(
    payload: TelegramAccountCreateRequest,
    session: DatabaseSession,
) -> TelegramAccountResponse:
    try:
        account = await TelegramAccountService(session).create_account(
            name=payload.display_name or payload.phone_number,
            phone_number=payload.phone_number,
        )
        account.is_enabled = payload.enabled
        if not payload.enabled:
            account.status = TelegramAccountStatus.DISABLED
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _account_response(account)


@router.post("/sessions/start", response_model=TelegramSessionChallengeResponse)
@limiter.limit("5/hour")
async def start_telegram_session(
    payload: TelegramSessionStartRequest,
    request: Request,
    session: DatabaseSession,
) -> TelegramSessionChallengeResponse:
    service = TelegramAccountService(session)
    account = await service.get_account(payload.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Telegram account was not found.")
    if not account.is_enabled:
        raise HTTPException(status_code=409, detail="Telegram account is disabled.")
    if payload.phone_number != account.phone_number:
        raise HTTPException(status_code=422, detail="Phone number does not match the account.")
    auth = getattr(request.app.state, "telegram_auth_service", None)
    if auth is None:
        raise HTTPException(status_code=503, detail="Telegram authentication is unavailable.")
    credentials = await _api_credentials(session)
    try:
        challenge = await auth.request_code(
            account.id,
            credentials.api_id,
            credentials.api_hash,
            account.phone_number,
        )
    except Exception as exc:
        await service.update_status(
            account.id,
            TelegramAccountStatus.ERROR,
            error=type(exc).__name__,
        )
        await session.commit()
        raise HTTPException(status_code=502, detail="Telegram login code request failed.") from exc
    await service.update_status(account.id, TelegramAccountStatus.CONNECTING)
    await session.commit()
    return TelegramSessionChallengeResponse(
        account_id=account.id,
        challenge_type=TelegramChallengeTypeSchema.PHONE_CODE,
        status=TelegramSessionStatusSchema.AWAITING_CODE,
        expires_at=challenge.expires_at,
        message="Telegram login code sent.",
    )


@router.post("/sessions/code", response_model=TelegramSessionChallengeResponse)
@limiter.limit("10/minute")
async def submit_telegram_code(
    payload: TelegramSessionCodeRequest,
    request: Request,
    session: DatabaseSession,
) -> TelegramSessionChallengeResponse:
    service = TelegramAccountService(session)
    account = await service.get_account(payload.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Telegram account was not found.")
    auth = getattr(request.app.state, "telegram_auth_service", None)
    if auth is None:
        raise HTTPException(status_code=503, detail="Telegram authentication is unavailable.")
    credentials = await _api_credentials(session)
    try:
        result = await auth.submit_code(
            account.id,
            credentials.api_id,
            credentials.api_hash,
            payload.phone_code,
        )
    except SessionPasswordNeededError:
        await service.update_status(account.id, TelegramAccountStatus.REQUIRES_2FA)
        await session.commit()
        return TelegramSessionChallengeResponse(
            account_id=account.id,
            challenge_type=TelegramChallengeTypeSchema.TWO_FACTOR_PASSWORD,
            status=TelegramSessionStatusSchema.AWAITING_PASSWORD,
            requires_password=True,
            message="Telegram requires the account's two-factor password.",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Telegram verification code was rejected.") from exc
    await _save_authenticated_session(request, session, account.id, result)
    await session.commit()
    return TelegramSessionChallengeResponse(
        account_id=account.id,
        challenge_type=TelegramChallengeTypeSchema.PHONE_CODE,
        status=TelegramSessionStatusSchema.CONNECTED,
        message="Telegram account connected.",
    )


@router.post("/sessions/password", response_model=TelegramSessionOperationResponse)
@limiter.limit("5/minute")
async def submit_telegram_password(
    payload: TelegramSessionPasswordRequest,
    request: Request,
    session: DatabaseSession,
) -> TelegramSessionOperationResponse:
    service = TelegramAccountService(session)
    account = await service.get_account(payload.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Telegram account was not found.")
    auth = getattr(request.app.state, "telegram_auth_service", None)
    if auth is None:
        raise HTTPException(status_code=503, detail="Telegram authentication is unavailable.")
    credentials = await _api_credentials(session)
    try:
        result = await auth.submit_password(
            account.id,
            credentials.api_id,
            credentials.api_hash,
            payload.password.get_secret_value(),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Telegram two-factor authentication failed.") from exc
    await _save_authenticated_session(request, session, account.id, result)
    await session.commit()
    return TelegramSessionOperationResponse(
        account_id=account.id,
        success=True,
        status=TelegramSessionStatusSchema.CONNECTED,
        message="Telegram account connected.",
    )


@router.post("/sessions/{account_id}/disconnect", response_model=TelegramSessionOperationResponse)
async def disconnect_telegram_session(
    account_id: int,
    request: Request,
    session: DatabaseSession,
) -> TelegramSessionOperationResponse:
    account_service = TelegramAccountService(session)
    account = await account_service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Telegram account was not found.")
    auth = getattr(request.app.state, "telegram_auth_service", None)
    manager = getattr(request.app.state, "telegram_client_manager", None)
    if auth is None or manager is None:
        raise HTTPException(status_code=503, detail="Telegram session management is unavailable.")
    await auth.logout(account_id)
    await account_service.clear_encrypted_session(account_id)
    await account_service.update_status(account_id, TelegramAccountStatus.DISCONNECTED)
    updates = getattr(request.app.state, "telegram_updates_service", None)
    if updates is not None:
        await updates.unregister_handlers(account_id)
    await session.commit()
    return TelegramSessionOperationResponse(
        account_id=account_id,
        success=True,
        status=TelegramSessionStatusSchema.DISCONNECTED,
        message="Telegram account disconnected.",
    )

