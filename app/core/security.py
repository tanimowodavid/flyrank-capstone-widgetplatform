"""Password hashing and access-token primitives.

Deliberately free of FastAPI imports: this module knows about credentials and
tokens, not about HTTP. Translating a failure into a 401 is the caller's job.
"""

from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext
from passlib.exc import UnknownHashError

from app.core.config import settings

# Bcrypt hashes only the first 72 bytes of a secret. passlib's default is to
# truncate silently, which would make two different long passwords interchangeable
# at login. Raising instead surfaces the problem; callers validate length first.
BCRYPT_MAX_BYTES = 72

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=True,
)


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of `plain`, salt included in the digest."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Check `plain` against `hashed`, returning False rather than raising.

    A malformed or empty stored hash means the credential can never match; that
    is an authentication failure, not a server error, so login must not 500 on it.
    """
    try:
        return pwd_context.verify(plain, hashed)
    except (UnknownHashError, ValueError):
        return False


class TokenError(Exception):
    """A token was missing, malformed, expired, or signed with another key.

    One exception for every failure mode on purpose: callers should not be able
    to branch on the reason, and clients should not learn it.
    """


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Sign an access token for `subject` (the customer's id).

    `expires_delta` overrides the configured lifetime; tests use it to mint an
    already-expired token without waiting.
    """
    now = datetime.now(UTC)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Verify signature and expiry, returning the claims.

    Raises TokenError on any problem. `algorithms` is pinned to the configured
    algorithm so a token cannot dictate how it is verified.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Could not validate credentials") from exc

    # A refresh token must not be accepted where an access token is required.
    if payload.get("type") != "access":
        raise TokenError("Could not validate credentials")

    return payload
