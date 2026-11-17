"""Initial administrator setup and session authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.csrf import (
    CSRF_COOKIE_NAME,
    create_signed_csrf_token,
    set_csrf_cookie,
)
from app.core.dependencies import CurrentUser, DatabaseSession
from app.core.rate_limiter import limiter
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import (
    AuthenticationResponse,
    AuthenticationStatusResponse,
    AuthenticationUserResponse,
    CSRFTokenResponse,
    InitialSetupRequest,
    InitialSetupStatusResponse,
    LoginRequest,
    LogoutResponse,
)
from app.services.authentication import (
    AuthenticationService,
    InitialSetupUnavailable,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def _issue_session(
    response: Response,
    user: User,
    *,
    max_age: int | None = None,
) -> AuthenticationResponse:
    settings = get_settings()
    lifetime = max_age or settings.session_max_age
    expires_at = datetime.now(UTC) + timedelta(
        seconds=lifetime
    )
    token = create_access_token(
        str(user.id),
        expires_delta=timedelta(seconds=lifetime),
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=lifetime,
        httponly=True,
        secure=settings.effective_session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return AuthenticationResponse(
        user=AuthenticationUserResponse.model_validate(user),
        expires_at=expires_at,
    )


@router.get("/csrf", response_model=CSRFTokenResponse)
async def get_csrf_token(response: Response) -> CSRFTokenResponse:
    """Set a signed CSRF cookie and return its matching header token."""
    settings = get_settings()
    token = create_signed_csrf_token()
    set_csrf_cookie(
        response,
        token=token,
        secure=settings.effective_session_cookie_secure,
    )
    response.headers["Cache-Control"] = "no-store"
    return CSRFTokenResponse(csrf_token=token)


@router.get("/setup/status", response_model=InitialSetupStatusResponse)
async def get_setup_status(
    session: DatabaseSession,
) -> InitialSetupStatusResponse:
    """Report whether initial administrator setup is available."""
    available = await AuthenticationService(
        session
    ).initial_setup_available()
    return InitialSetupStatusResponse(setup_required=available)


@router.post(
    "/setup",
    response_model=AuthenticationResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("3/minute")
async def create_initial_admin(
    request: Request,
    payload: InitialSetupRequest,
    response: Response,
    session: DatabaseSession,
) -> AuthenticationResponse:
    """Create the first superuser exactly once and sign it in."""
    service = AuthenticationService(session)
    try:
        user = await service.create_initial_admin(
            username=payload.username,
            email=str(payload.email),
            display_name=payload.display_name,
            password=payload.password.get_secret_value(),
        )
        await session.commit()
    except InitialSetupUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Initial administrator setup is already complete.",
        ) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The supplied username or email is already in use.",
        ) from exc
    return _issue_session(response, user)


@router.post("/login", response_model=AuthenticationResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    session: DatabaseSession,
) -> AuthenticationResponse:
    """Verify account credentials and issue an HttpOnly session cookie."""
    user = await AuthenticationService(session).authenticate(
        payload.username,
        payload.password.get_secret_value(),
    )
    if user is None:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await session.commit()
    settings = get_settings()
    lifetime = (
        settings.session_max_age
        if payload.remember_me
        else min(settings.session_max_age, 3600)
    )
    return _issue_session(response, user, max_age=lifetime)


@router.get(
    "/me",
    response_model=AuthenticationStatusResponse,
)
async def get_authentication_status(
    current_user: CurrentUser,
) -> AuthenticationStatusResponse:
    """Return safe profile information for the current session."""
    return AuthenticationStatusResponse(
        authenticated=True,
        user=AuthenticationUserResponse.model_validate(current_user),
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(response: Response) -> LogoutResponse:
    """Clear authentication and CSRF cookies in the browser."""
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.effective_session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        secure=settings.effective_session_cookie_secure,
        httponly=False,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return LogoutResponse()

