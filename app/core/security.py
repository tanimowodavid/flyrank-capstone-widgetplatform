"""Password hashing primitives.

Bcrypt via passlib. The CryptContext is built once at import: each construction
re-runs passlib's backend probing, which is wasted work per call.
"""

from passlib.context import CryptContext
from passlib.exc import UnknownHashError

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
