"""Data access for customers. Owns queries; owns no business rules."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, customer_id: uuid.UUID) -> Customer | None:
        result = await self.session.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Customer | None:
        """Look up by email, case-insensitively.

        Emails are stored lowercased by the service layer, so a plain equality
        match on an already-lowercased argument hits the unique index.
        """
        result = await self.session.execute(
            select(Customer).where(Customer.email == email)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        organization_name: str,
        email: str,
        password_hash: str,
    ) -> Customer:
        customer = Customer(
            organization_name=organization_name,
            email=email,
            password_hash=password_hash,
        )
        self.session.add(customer)
        await self.session.flush()
        # Server-generated id/created_at are not populated until the row is read
        # back; refresh so the caller gets a fully materialised object.
        await self.session.refresh(customer)
        return customer

    async def delete_by_id(self, customer_id: uuid.UUID) -> None:
        """Delete a customer row, letting the database cascade to its children.

        A Core DELETE rather than session.delete(instance): the ORM path would
        cascade in Python, and the point of the ON DELETE CASCADE on widgets and
        submissions is that the database owns that behaviour.
        """
        await self.session.execute(delete(Customer).where(Customer.id == customer_id))
