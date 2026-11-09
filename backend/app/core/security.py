
"""
TeleForward security utilities.

Provides password hashing, cryptographic secret generation,
encryption at rest, and JWT access-token operations.

Security-sensitive operations require explicitly configured
keys. The application must never silently substitute temporary
or predictable secrets.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

from app.core.config import get_settings


# ------------------------------------------------------------
# Password hashing
# ------------------------------------------------------------

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """
    Hash a password using the recommended Argon2 configuration.

    Args:
        password: Plain-text password.

    Returns:
        Secure password hash suitable for database storage.
    """
    if not password:
        raise ValueError("Password cannot be empty.")

    if len(password.encode("utf-8")) > 1024:
        raise ValueError("Password exceeds the maximum supported length.")

    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against its stored hash.

    Args:
        password: Plain-text password supplied during login.
        password_hash: Previously stored password hash.

    Returns:
        True if the password matches; otherwise False.
    """
    if not password or not password_hash:
        return False

    if len(password.encode("utf-8")) > 1024:
        return False

    return _password_hasher.verify(password, password_hash)


# ------------------------------------------------------------
# Cryptographic secret generation
# ------------------------------------------------------------

def generate_secret(length: int = 48) -> str:
    """
    Generate a cryptographically secure random secret.

    Args:
        length: Number of random bytes used to generate the secret.

    Returns:
        URL-safe random secret.
    """
    if length < 32:
        raise ValueError("Secret length must be at least 32 bytes.")

    return secrets.token_urlsafe(length)


def generate_encryption_key() -> str:
    """
    Generate a new Fernet-compatible encryption key.

    The generated key must be stored securely and remain
    unchanged while encrypted application data depends on it.
    """
    return Fernet.generate_key().decode("ascii")


# ------------------------------------------------------------
# Secret configuration
# ------------------------------------------------------------

def _get_configured_secret(
    secret_name: str,
    minimum_length: int = 32,
) -> str:
    """
    Retrieve and validate a configured application secret.

    Secrets are deliberately not generated automatically.
    """
    settings = get_settings()
    configured_secret = getattr(settings, secret_name, None)

    if configured_secret is None:
        raise RuntimeError(
            f"{secret_name} is not configured. "
            "Complete the TeleForward security setup first."
        )

    secret_value = configured_secret.get_secret_value()

    if len(secret_value) < minimum_length:
        raise RuntimeError(
            f"{secret_name} must contain at least "
            f"{minimum_length} characters."
        )

    return secret_value


def _get_encryption_cipher() -> Fernet:
    """
    Construct the Fernet cipher using the configured encryption key.

    Invalid encryption keys cause an explicit configuration error.
    """
    key = _get_configured_secret(
        "encryption_key",
        minimum_length=1,
    )

    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError(
            "The configured encryption key is invalid. "
            "A valid Fernet key is required."
        ) from exc


# ------------------------------------------------------------
# Encryption at rest
# ------------------------------------------------------------

def encrypt_value(value: str) -> str:
    """
    Encrypt a string using Fernet authenticated encryption.

    Args:
        value: Sensitive plain-text value.

    Returns:
        URL-safe encrypted token suitable for database storage.
    """
    if not isinstance(value, str):
        raise TypeError("Only string values can be encrypted.")

    if not value:
        raise ValueError("Cannot encrypt an empty value.")

    cipher = _get_encryption_cipher()

    encrypted = cipher.encrypt(value.encode("utf-8"))

    return encrypted.decode("ascii")


def decrypt_value(encrypted_value: str) -> str:
    """
    Decrypt a previously encrypted string.

    Args:
        encrypted_value: Fernet token stored in the database.

    Returns:
        Original plain-text value.

    Raises:
        ValueError: If the token is invalid or authentication fails.
    """
    if not encrypted_value:
        raise ValueError("Encrypted value cannot be empty.")

    cipher = _get_encryption_cipher()

    try:
        decrypted = cipher.decrypt(
            encrypted_value.encode("ascii")
        )

        return decrypted.decode("utf-8")

    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(
            "Unable to decrypt the supplied value. "
            "The data may be corrupted or the encryption key may "
            "not match the key used during encryption."
        ) from exc


# ------------------------------------------------------------
# JWT access tokens
# ------------------------------------------------------------

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "teleforward"


def create_access_token(
    subject: str,
    expires_delta: timedelta = timedelta(minutes=30),
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject: Unique identifier of the authenticated user.
        expires_delta: Token lifetime.
        additional_claims: Optional non-reserved JWT claims.

    Returns:
        Signed JWT string.
    """
    if not subject or not subject.strip():
        raise ValueError("Token subject cannot be empty.")

    if expires_delta.total_seconds() <= 0:
        raise ValueError("Token lifetime must be positive.")

    reserved_claims = {
        "sub",
        "iat",
        "exp",
        "iss",
        "jti",
    }

    extra_claims = additional_claims or {}

    if reserved_claims.intersection(extra_claims):
        raise ValueError(
            "Additional claims cannot override reserved JWT claims."
        )

    now = datetime.now(UTC)

    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + expires_delta,
        "iss": JWT_ISSUER,
        "jti": secrets.token_urlsafe(16),
    }

    payload.update(extra_claims)

    signing_key = _get_configured_secret("jwt_secret_key")

    return jwt.encode(
        payload,
        signing_key,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Verify and decode a JWT access token.

    Signature, expiration and issuer are validated.

    Args:
        token: JWT access token.

    Returns:
        Decoded token claims.

    Raises:
        ValueError: If the token is invalid or expired.
    """
    if not token:
        raise ValueError("Access token cannot be empty.")

    signing_key = _get_configured_secret("jwt_secret_key")

    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={
                "require": [
                    "sub",
                    "iat",
                    "exp",
                    "iss",
                    "jti",
                ],
            },
        )

        return payload

    except jwt.InvalidTokenError as exc:
        raise ValueError(
            "Invalid or expired access token."
        ) from exc
