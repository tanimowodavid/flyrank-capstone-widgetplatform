"""Authentication business rules: signup, credential checking, token issuing.

Raises domain errors rather than HTTPException — mapping to status codes belongs
in the endpoint layer.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.models.customer import Customer
from app.repositories.customer import CustomerRepository
from app.schemas.customer import CustomerLogin, CustomerSignup

# Verified against when no customer matches, so a missing email costs the same
# bcrypt work as a wrong password. Without this, response time alone tells an
# attacker which emails are registered.
_DUMMY_HASH = hash_password("timing-equalisation-placeholder")


class EmailAlreadyRegisteredError(Exception):
    """Signup used an email that already belongs to a customer."""


class InvalidCredentialsError(Exception):
    """Email is unknown or the password is wrong — caller must not learn which."""


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.customers = CustomerRepository(session)

    async def signup(self, payload: CustomerSignup) -> Customer:
        email = self._normalize_email(payload.email)

        if await self.customers.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError(email)

        customer = await self.customers.create(
            organization_name=payload.organization_name,
            email=email,
            password_hash=hash_password(payload.password),
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            # Two concurrent signups can both pass the check above; the unique
            # index is what actually decides, so treat its violation as the
            # same conflict rather than a 500.
            await self.session.rollback()
            raise EmailAlreadyRegisteredError(email) from exc

        return customer

    async def authenticate(self, payload: CustomerLogin) -> Customer:
        email = self._normalize_email(payload.email)
        customer = await self.customers.get_by_email(email)

        if customer is None:
            verify_password(payload.password, _DUMMY_HASH)
            raise InvalidCredentialsError

        if not verify_password(payload.password, customer.password_hash):
            raise InvalidCredentialsError

        return customer

    def issue_access_token(self, customer: Customer) -> str:
        return create_access_token(subject=str(customer.id))

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Lowercase and strip, so "A@x.com " and "a@x.com" are one account.

        Applied on both signup and login; otherwise a customer could register a
        second account differing only in case, or fail to log in after typing
        their address with different capitalisation.
        """
        return email.strip().lower()
