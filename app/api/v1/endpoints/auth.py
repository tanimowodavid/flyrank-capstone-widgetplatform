"""Signup, login, and authenticated account management."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.deps import CurrentCustomer, DbSession
from app.core.rate_limit import limiter
from app.schemas.customer import (
    CustomerLogin,
    CustomerPasswordChange,
    CustomerRead,
    CustomerSignup,
    CustomerUpdate,
    Token,
)
from app.services.auth import (
    AuthService,
    EmailAlreadyRegisteredError,
    IncorrectPasswordError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Register a customer and return an access token",
)
async def signup(payload: CustomerSignup, db: DbSession) -> Token:
    service = AuthService(db)
    try:
        customer = await service.signup(payload)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc

    return Token(access_token=service.issue_access_token(customer))


@router.post(
    "/login",
    response_model=Token,
    summary="Exchange credentials for an access token",
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    request: Request, response: Response, payload: CustomerLogin, db: DbSession
) -> Token:
    """Rate limited per IP: this is the endpoint an attacker brute-forces.

    The limit counts every attempt, successful or not — counting only failures
    would let a caller reset their own budget with one valid login.

    `request` and `response` are required by the limiter, not by this handler:
    slowapi reads the caller's IP off the request and writes the X-RateLimit-*
    headers onto the response.
    """
    service = AuthService(db)
    try:
        customer = await service.authenticate(payload)
    except InvalidCredentialsError as exc:
        # One message for both unknown-email and wrong-password: anything more
        # specific turns this endpoint into an account-enumeration oracle.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return Token(access_token=service.issue_access_token(customer))


@router.get(
    "/me",
    response_model=CustomerRead,
    summary="Return the authenticated customer",
)
async def read_current_customer(customer: CurrentCustomer) -> CustomerRead:
    return CustomerRead.model_validate(customer)


@router.patch(
    "/me",
    response_model=CustomerRead,
    summary="Update the authenticated customer's profile",
)
async def update_current_customer(
    payload: CustomerUpdate,
    customer: CurrentCustomer,
    db: DbSession,
) -> CustomerRead:
    service = AuthService(db)
    try:
        updated = await service.update_profile(customer, payload)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc

    return CustomerRead.model_validate(updated)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete the authenticated customer's account",
)
async def delete_current_customer(customer: CurrentCustomer, db: DbSession) -> None:
    await AuthService(db).delete_account(customer)


@router.post(
    "/change-password",
    response_model=CustomerRead,
    summary="Change the authenticated customer's password",
)
async def change_password(
    payload: CustomerPasswordChange,
    customer: CurrentCustomer,
    db: DbSession,
) -> CustomerRead:
    service = AuthService(db)
    try:
        updated = await service.change_password(customer, payload)
    except IncorrectPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        ) from exc

    return CustomerRead.model_validate(updated)
