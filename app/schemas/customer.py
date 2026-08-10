"""Request and response schemas for customers and authentication."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.security import BCRYPT_MAX_BYTES


class CustomerSignup(BaseModel):
    organization_name: str = Field(min_length=1, max_length=255)
    email: EmailStr = Field(max_length=255)
    # Capped at bcrypt's limit: passlib is configured to raise rather than
    # truncate, so an over-long password must fail validation as a 422 here
    # instead of blowing up inside the hasher as a 500.
    password: str = Field(min_length=8, max_length=BCRYPT_MAX_BYTES)


class CustomerLogin(BaseModel):
    email: EmailStr
    # No min_length: a length rule on login would reject a short legacy password
    # before it could be checked, and hints at the policy to anyone probing.
    password: str


class CustomerPasswordChange(BaseModel):
    # current_password is unconstrained for the same reason as CustomerLogin's:
    # it is checked against the stored hash, not against today's policy.
    current_password: str
    new_password: str = Field(min_length=8, max_length=BCRYPT_MAX_BYTES)


class CustomerRead(BaseModel):
    """Customer as returned to clients. password_hash is deliberately absent."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_name: str
    email: EmailStr
    created_at: datetime
    updated_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
