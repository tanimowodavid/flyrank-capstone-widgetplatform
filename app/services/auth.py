"""Authentication business rules: signup, credential checking, token issuing.

Raises domain errors rather than HTTPException — mapping to status codes belongs
in the endpoint layer.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.models.customer import Customer
from app.repositories.customer import CustomerRepository
from app.schemas.customer import (
    CustomerLogin,
    CustomerPasswordChange,
    CustomerSignup,
    CustomerUpdate,
)

# Verified against when no customer matches, so a missing email costs the same
# bcrypt work as a wrong password. Without this, response time alone tells an
# attacker which emails are registered.
_DUMMY_HASH = hash_password("timing-equalisation-placeholder")


class EmailAlreadyRegisteredError(Exception):
    """Signup used an email that already belongs to a customer."""


class InvalidCredentialsError(Exception):
    """Email is unknown or the password is wrong — caller must not learn which."""


class IncorrectPasswordError(Exception):
    """The supplied current password did not match the stored hash.

    Distinct from InvalidCredentialsError: the caller is already authenticated,
    so naming the failing field is not an enumeration risk here.
    """


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

    async def update_profile(
        self,
        customer: Customer,
        payload: CustomerUpdate,
    ) -> Customer:
        """Apply a partial profile update.

        Only fields the client actually sent are touched, so omitting a field
        leaves it alone rather than overwriting it with None.
        """
        fields = payload.model_dump(exclude_unset=True)

        if "organization_name" in fields:
            customer.organization_name = fields["organization_name"]

        if "email" in fields:
            email = self._normalize_email(fields["email"])
            # Same uniqueness rule as signup. Skipped when the address is
            # unchanged, otherwise a no-op update would collide with itself.
            if email != customer.email:
                if await self.customers.get_by_email(email) is not None:
                    raise EmailAlreadyRegisteredError(email)
                customer.email = email

        # Read before commit: rollback expires the instance, and re-reading an
        # expired attribute would emit lazy IO that raises inside the handler.
        attempted_email = customer.email

        try:
            await self.session.commit()
        except IntegrityError as exc:
            # Mirrors signup: the unique index is the real arbiter under
            # concurrent updates, so its violation is the same conflict.
            await self.session.rollback()
            raise EmailAlreadyRegisteredError(attempted_email) from exc

        await self.session.refresh(customer)
        return customer

    async def change_password(
        self,
        customer: Customer,
        payload: CustomerPasswordChange,
    ) -> Customer:
        """Re-verify the current password, then replace the stored hash.

        Holding a valid token is not sufficient: a borrowed or stolen token must
        not be enough to lock the real owner out of their account, so the current
        password is proved again here regardless of authentication state.
        """
        if not verify_password(payload.current_password, customer.password_hash):
            raise IncorrectPasswordError

        customer.password_hash = hash_password(payload.new_password)
        await self.session.commit()
        await self.session.refresh(customer)
        return customer

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Lowercase and strip, so "A@x.com " and "a@x.com" are one account.

        Applied on both signup and login; otherwise a customer could register a
        second account differing only in case, or fail to log in after typing
        their address with different capitalisation.
        """
        return email.strip().lower()
