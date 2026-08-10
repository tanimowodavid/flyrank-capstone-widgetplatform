"""Tests for signup, login, and the get_current_customer dependency."""

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.models.customer import Customer
from app.models.form_field import FormField
from app.models.submission import Submission
from app.models.widget import Widget

# No asyncio marker: pyproject sets asyncio_mode = "auto".

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
CHANGE_PASSWORD_URL = "/api/v1/auth/change-password"

OTHER_EMAIL = "rival@other.example"

PASSWORD = "correct-horse-battery"


def signup_payload(**overrides) -> dict:
    payload = {
        "organization_name": "Acme Widgets",
        "email": "owner@acme.example",
        "password": PASSWORD,
    }
    payload.update(overrides)
    return payload


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestSignup:
    async def test_signup_succeeds_and_returns_token(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(SIGNUP_URL, json=signup_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

        customer = (
            await db_session.execute(
                select(Customer).where(Customer.email == "owner@acme.example")
            )
        ).scalar_one()
        assert customer.organization_name == "Acme Widgets"
        assert customer.created_at is not None

    async def test_signup_stores_a_hash_not_the_password(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())

        customer = (await db_session.execute(select(Customer))).scalar_one()
        assert customer.password_hash != PASSWORD
        assert verify_password(PASSWORD, customer.password_hash)

    async def test_duplicate_email_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        first = await client.post(SIGNUP_URL, json=signup_payload())
        assert first.status_code == 201

        second = await client.post(
            SIGNUP_URL, json=signup_payload(organization_name="Impostor")
        )

        assert second.status_code == 409
        assert second.json()["detail"] == "Email already registered"

        # The conflict must not have created a second row or altered the first.
        customers = (await db_session.execute(select(Customer))).scalars().all()
        assert len(customers) == 1
        assert customers[0].organization_name == "Acme Widgets"

    async def test_duplicate_email_is_rejected_regardless_of_case(
        self, client: AsyncClient
    ) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())

        response = await client.post(
            SIGNUP_URL, json=signup_payload(email="OWNER@ACME.EXAMPLE")
        )

        assert response.status_code == 409

    @pytest.mark.parametrize(
        "overrides",
        [
            {"email": "not-an-email"},
            {"password": "short"},
            {"password": "x" * 73},  # over bcrypt's 72-byte limit
            {"organization_name": ""},
        ],
    )
    async def test_invalid_signup_is_rejected(
        self, client: AsyncClient, overrides: dict
    ) -> None:
        response = await client.post(SIGNUP_URL, json=signup_payload(**overrides))

        assert response.status_code == 422


class TestLogin:
    async def test_login_succeeds_with_correct_credentials(
        self, client: AsyncClient
    ) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())

        response = await client.post(
            LOGIN_URL, json={"email": "owner@acme.example", "password": PASSWORD}
        )

        assert response.status_code == 200
        assert response.json()["access_token"]
        assert response.json()["token_type"] == "bearer"

    async def test_login_accepts_a_differently_cased_email(
        self, client: AsyncClient
    ) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())

        response = await client.post(
            LOGIN_URL, json={"email": "Owner@Acme.EXAMPLE", "password": PASSWORD}
        )

        assert response.status_code == 200

    async def test_wrong_password_is_rejected(self, client: AsyncClient) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())

        response = await client.post(
            LOGIN_URL, json={"email": "owner@acme.example", "password": "not-my-password"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"
        assert "access_token" not in response.json()

    async def test_failure_does_not_reveal_whether_the_email_exists(
        self, client: AsyncClient
    ) -> None:
        """Wrong password and unknown email must be indistinguishable."""
        await client.post(SIGNUP_URL, json=signup_payload())

        wrong_password = await client.post(
            LOGIN_URL, json={"email": "owner@acme.example", "password": "not-my-password"}
        )
        unknown_email = await client.post(
            LOGIN_URL, json={"email": "nobody@acme.example", "password": PASSWORD}
        )

        assert wrong_password.status_code == unknown_email.status_code == 401
        assert wrong_password.json() == unknown_email.json()


class TestGetCurrentCustomer:
    async def test_valid_token_is_accepted(self, client: AsyncClient) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.get(ME_URL, headers=auth_header(token))

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "owner@acme.example"
        assert body["organization_name"] == "Acme Widgets"
        assert "password_hash" not in body
        assert "password" not in body

    async def test_token_from_login_is_accepted(self, client: AsyncClient) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())
        token = (
            await client.post(
                LOGIN_URL, json={"email": "owner@acme.example", "password": PASSWORD}
            )
        ).json()["access_token"]

        response = await client.get(ME_URL, headers=auth_header(token))

        assert response.status_code == 200

    async def test_expired_token_is_rejected(self, client: AsyncClient) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        me = await client.get(ME_URL, headers=auth_header(token))
        assert me.status_code == 200, "token must work before it expires"

        customer_id = me.json()["id"]
        expired = create_access_token(
            subject=customer_id, expires_delta=timedelta(minutes=-1)
        )

        response = await client.get(ME_URL, headers=auth_header(expired))

        assert response.status_code == 401
        assert response.json()["detail"] == "Could not validate credentials"

    @pytest.mark.parametrize(
        ("label", "headers"),
        [
            ("no header", {}),
            ("empty bearer", {"Authorization": "Bearer "}),
            ("malformed token", {"Authorization": "Bearer garbage.token.here"}),
            ("not a jwt", {"Authorization": "Bearer abc123"}),
            ("wrong scheme", {"Authorization": f"Basic {create_access_token('x')}"}),
        ],
    )
    async def test_invalid_credentials_are_rejected(
        self, client: AsyncClient, label: str, headers: dict
    ) -> None:
        response = await client.get(ME_URL, headers=headers)

        assert response.status_code == 401, label

    async def test_token_signed_with_another_key_is_rejected(
        self, client: AsyncClient
    ) -> None:
        """Guards against accepting a token the server did not sign."""
        import jwt

        from app.core.config import settings

        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        claims = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        # 32+ bytes only to avoid PyJWT's short-key warning; the point is that
        # this key is not the server's.
        forged = jwt.encode(claims, "an-attacker-secret-long-enough-to-sign", algorithm="HS256")

        response = await client.get(ME_URL, headers=auth_header(forged))

        assert response.status_code == 401

    async def test_token_for_a_deleted_customer_is_rejected(
        self, client: AsyncClient
    ) -> None:
        """A well-formed token whose subject no longer exists must not authenticate."""
        token = create_access_token(subject=str(uuid.uuid4()))

        response = await client.get(ME_URL, headers=auth_header(token))

        assert response.status_code == 401


NEW_PASSWORD = "a-brand-new-passphrase"


class TestChangePassword:
    async def test_password_change_succeeds(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.post(
            CHANGE_PASSWORD_URL,
            headers=auth_header(token),
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )

        assert response.status_code == 200
        assert "password_hash" not in response.json()

        customer = (await db_session.execute(select(Customer))).scalar_one()
        assert verify_password(NEW_PASSWORD, customer.password_hash)
        assert not verify_password(PASSWORD, customer.password_hash)

    async def test_new_password_works_at_login_and_old_one_does_not(
        self, client: AsyncClient
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        await client.post(
            CHANGE_PASSWORD_URL,
            headers=auth_header(token),
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )

        with_new = await client.post(
            LOGIN_URL, json={"email": "owner@acme.example", "password": NEW_PASSWORD}
        )
        with_old = await client.post(
            LOGIN_URL, json={"email": "owner@acme.example", "password": PASSWORD}
        )

        assert with_new.status_code == 200
        assert with_new.json()["access_token"]
        assert with_old.status_code == 401

    async def test_wrong_current_password_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Being authenticated is not enough — the old password must still be proved."""
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.post(
            CHANGE_PASSWORD_URL,
            headers=auth_header(token),
            json={"current_password": "not-my-password", "new_password": NEW_PASSWORD},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Current password is incorrect"

        # The stored hash must be untouched by the rejected attempt.
        customer = (await db_session.execute(select(Customer))).scalar_one()
        assert verify_password(PASSWORD, customer.password_hash)
        assert not verify_password(NEW_PASSWORD, customer.password_hash)

    async def test_unauthenticated_request_is_rejected(
        self, client: AsyncClient
    ) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())

        response = await client.post(
            CHANGE_PASSWORD_URL,
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "new_password",
        ["short", "x" * 73],  # under the minimum, then over bcrypt's 72-byte limit
    )
    async def test_invalid_new_password_is_rejected(
        self, client: AsyncClient, new_password: str
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.post(
            CHANGE_PASSWORD_URL,
            headers=auth_header(token),
            json={"current_password": PASSWORD, "new_password": new_password},
        )

        assert response.status_code == 422


class TestUpdateProfile:
    async def test_organization_name_is_updated(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.patch(
            ME_URL,
            headers=auth_header(token),
            json={"organization_name": "Acme Renamed"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["organization_name"] == "Acme Renamed"
        # Untouched field must survive a partial update.
        assert body["email"] == "owner@acme.example"
        assert "password_hash" not in body

        customer = (await db_session.execute(select(Customer))).scalar_one()
        assert customer.organization_name == "Acme Renamed"

    async def test_email_is_updated_and_usable_at_login(
        self, client: AsyncClient
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.patch(
            ME_URL, headers=auth_header(token), json={"email": OTHER_EMAIL}
        )

        assert response.status_code == 200
        assert response.json()["email"] == OTHER_EMAIL

        with_new = await client.post(
            LOGIN_URL, json={"email": OTHER_EMAIL, "password": PASSWORD}
        )
        with_old = await client.post(
            LOGIN_URL, json={"email": "owner@acme.example", "password": PASSWORD}
        )

        assert with_new.status_code == 200
        assert with_old.status_code == 401

    async def test_both_fields_update_together(self, client: AsyncClient) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.patch(
            ME_URL,
            headers=auth_header(token),
            json={"organization_name": "Both Changed", "email": OTHER_EMAIL},
        )

        assert response.status_code == 200
        assert response.json()["organization_name"] == "Both Changed"
        assert response.json()["email"] == OTHER_EMAIL

    async def test_email_taken_by_another_customer_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        await client.post(
            SIGNUP_URL,
            json=signup_payload(email=OTHER_EMAIL, organization_name="Rival"),
        )

        response = await client.patch(
            ME_URL, headers=auth_header(token), json={"email": OTHER_EMAIL}
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "Email already registered"

        # The rejected update must not have altered the original row.
        customer = (
            await db_session.execute(
                select(Customer).where(Customer.email == "owner@acme.example")
            )
        ).scalar_one()
        assert customer.organization_name == "Acme Widgets"

    async def test_taken_email_is_rejected_regardless_of_case(
        self, client: AsyncClient
    ) -> None:
        """Uniqueness must survive casing, exactly as it does at signup."""
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        await client.post(
            SIGNUP_URL,
            json=signup_payload(email=OTHER_EMAIL, organization_name="Rival"),
        )

        response = await client.patch(
            ME_URL, headers=auth_header(token), json={"email": OTHER_EMAIL.upper()}
        )

        assert response.status_code == 409

    async def test_reclaiming_your_own_email_is_allowed(
        self, client: AsyncClient
    ) -> None:
        """Submitting the unchanged address must not collide with yourself."""
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.patch(
            ME_URL,
            headers=auth_header(token),
            json={"email": "owner@acme.example", "organization_name": "Same Email"},
        )

        assert response.status_code == 200
        assert response.json()["organization_name"] == "Same Email"

    async def test_email_is_normalized_before_storage(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.patch(
            ME_URL, headers=auth_header(token), json={"email": "  MiXeD@Case.EXAMPLE  "}
        )

        assert response.status_code == 200
        customer = (await db_session.execute(select(Customer))).scalar_one()
        assert customer.email == "mixed@case.example"

    async def test_unauthenticated_request_is_rejected(
        self, client: AsyncClient
    ) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())

        response = await client.patch(ME_URL, json={"organization_name": "Nope"})

        assert response.status_code == 401

    @pytest.mark.parametrize(
        ("label", "payload"),
        [
            ("empty body", {}),
            ("unknown field only", {"organizationName": "typo'd key"}),
            ("null organization_name", {"organization_name": None}),
            ("null email", {"email": None}),
            ("blank organization_name", {"organization_name": ""}),
            ("invalid email", {"email": "not-an-email"}),
        ],
    )
    async def test_invalid_update_is_rejected(
        self, client: AsyncClient, label: str, payload: dict
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.patch(ME_URL, headers=auth_header(token), json=payload)

        assert response.status_code == 422, label


async def seed_widget_tree(
    session: AsyncSession, customer_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Insert a widget with one form field and one submission for `customer_id`.

    Widget endpoints do not exist yet, so the cascade tests build the child rows
    directly. Returns the three ids so a test can assert they are gone.
    """
    widget = Widget(
        customer_id=customer_id,
        widget_type="signup_form",
        title="Newsletter Signup",
    )
    session.add(widget)
    await session.flush()

    form_field = FormField(
        widget_id=widget.id,
        field_name="email",
        label="Email address",
        field_type="email",
    )
    submission = Submission(
        widget_id=widget.id,
        customer_id=customer_id,
        payload={"email": "visitor@example.com"},
    )
    session.add_all([form_field, submission])
    await session.commit()

    return widget.id, form_field.id, submission.id


class TestDeleteAccount:
    async def test_delete_removes_the_customer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]

        response = await client.delete(ME_URL, headers=auth_header(token))

        assert response.status_code == 204
        assert not response.content

        remaining = (await db_session.execute(select(Customer))).scalars().all()
        assert remaining == []

    async def test_delete_cascades_to_widgets_and_submissions(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The database's ON DELETE CASCADE must clear the whole owned tree."""
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        customer_id = uuid.UUID(
            (await client.get(ME_URL, headers=auth_header(token))).json()["id"]
        )
        widget_id, form_field_id, submission_id = await seed_widget_tree(
            db_session, customer_id
        )

        response = await client.delete(ME_URL, headers=auth_header(token))

        assert response.status_code == 204

        # Read through a fresh transaction so these are not served from identity map.
        await db_session.commit()
        assert await db_session.get(Widget, widget_id) is None
        assert await db_session.get(FormField, form_field_id) is None
        assert await db_session.get(Submission, submission_id) is None

    async def test_delete_leaves_other_customers_untouched(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Tenant isolation: one account's deletion must not touch another's data."""
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        other_token = (
            await client.post(
                SIGNUP_URL,
                json=signup_payload(email=OTHER_EMAIL, organization_name="Rival"),
            )
        ).json()["access_token"]

        other_id = uuid.UUID(
            (await client.get(ME_URL, headers=auth_header(other_token))).json()["id"]
        )
        other_widget_id, _, other_submission_id = await seed_widget_tree(
            db_session, other_id
        )

        response = await client.delete(ME_URL, headers=auth_header(token))

        assert response.status_code == 204

        await db_session.commit()
        assert await db_session.get(Widget, other_widget_id) is not None
        assert await db_session.get(Submission, other_submission_id) is not None
        assert await db_session.get(Customer, other_id) is not None

    async def test_deleted_customer_cannot_log_in(self, client: AsyncClient) -> None:
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        await client.delete(ME_URL, headers=auth_header(token))

        response = await client.post(
            LOGIN_URL, json={"email": "owner@acme.example", "password": PASSWORD}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    async def test_token_stops_working_after_deletion(
        self, client: AsyncClient
    ) -> None:
        """The subject row is gone, so the still-unexpired token must not resolve."""
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        await client.delete(ME_URL, headers=auth_header(token))

        response = await client.get(ME_URL, headers=auth_header(token))

        assert response.status_code == 401

    async def test_email_is_reusable_after_deletion(self, client: AsyncClient) -> None:
        """A hard delete frees the address; the unique index must not block reuse."""
        token = (await client.post(SIGNUP_URL, json=signup_payload())).json()[
            "access_token"
        ]
        await client.delete(ME_URL, headers=auth_header(token))

        response = await client.post(SIGNUP_URL, json=signup_payload())

        assert response.status_code == 201

    async def test_unauthenticated_request_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await client.post(SIGNUP_URL, json=signup_payload())

        response = await client.delete(ME_URL)

        assert response.status_code == 401
        # The account must still be there.
        assert (await db_session.execute(select(Customer))).scalar_one() is not None
