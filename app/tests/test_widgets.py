"""Tests for widget creation, listing and retrieval.

Ownership is the property under test throughout: a widget belongs to the caller
identified by the access token, nothing in the request body can change that, and
another tenant's widget is indistinguishable from one that does not exist.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.form_field import FormField
from app.models.widget import Widget

SIGNUP_URL = "/api/v1/auth/signup"
WIDGETS_URL = "/api/v1/widgets"

PASSWORD = "correct-horse-battery"


def signup_payload(**overrides) -> dict:
    payload = {
        "organization_name": "Acme Widgets",
        "email": "owner@acme.example",
        "password": PASSWORD,
    }
    payload.update(overrides)
    return payload


def widget_payload(**overrides) -> dict:
    payload = {
        "widget_type": "signup_form",
        "title": "Newsletter Signup",
        "description": "Join our list",
        "button_text": "Subscribe",
        "theme_color": "#3366ff",
        "form_fields": [
            {
                "field_name": "email",
                "label": "Email address",
                "field_type": "email",
                "placeholder": "you@example.com",
                "is_required": True,
                "display_order": 0,
            },
            {
                "field_name": "full_name",
                "label": "Full name",
                "field_type": "text",
                "is_required": False,
                "display_order": 1,
            },
        ],
    }
    payload.update(overrides)
    return payload


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client: AsyncClient, **overrides) -> str:
    """Sign up and return the access token."""
    response = await client.post(SIGNUP_URL, json=signup_payload(**overrides))
    assert response.status_code == 201
    return response.json()["access_token"]


async def register_other(client: AsyncClient) -> str:
    """Sign up a second, unrelated customer — the cross-tenant counterparty."""
    return await register(
        client, email="rival@other.example", organization_name="Other Co"
    )


async def create_widget(client: AsyncClient, token: str, **overrides) -> dict:
    """Create a widget as `token`'s owner and return the response body."""
    response = await client.post(
        WIDGETS_URL, headers=auth_header(token), json=widget_payload(**overrides)
    )
    assert response.status_code == 201
    return response.json()


class TestCreateWidget:
    async def test_widget_is_created_with_its_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)

        response = await client.post(
            WIDGETS_URL, headers=auth_header(token), json=widget_payload()
        )

        assert response.status_code == 201
        body = response.json()
        assert body["widget_type"] == "signup_form"
        assert body["title"] == "Newsletter Signup"
        assert body["description"] == "Join our list"
        assert body["button_text"] == "Subscribe"
        assert body["theme_color"] == "#3366ff"
        assert body["is_active"] is True
        assert body["id"]
        assert body["created_at"]

        fields = body["form_fields"]
        assert len(fields) == 2
        assert [field["field_name"] for field in fields] == ["email", "full_name"]
        assert fields[0]["label"] == "Email address"
        assert fields[0]["field_type"] == "email"
        assert fields[0]["placeholder"] == "you@example.com"
        assert fields[0]["is_required"] is True
        assert fields[1]["is_required"] is False

        stored = (await db_session.execute(select(Widget))).scalar_one()
        assert stored.title == "Newsletter Signup"
        stored_fields = (await db_session.execute(select(FormField))).scalars().all()
        assert len(stored_fields) == 2

    async def test_widget_is_owned_by_the_authenticated_customer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        me = await client.get("/api/v1/auth/me", headers=auth_header(token))
        customer_id = me.json()["id"]

        response = await client.post(
            WIDGETS_URL, headers=auth_header(token), json=widget_payload()
        )

        assert response.status_code == 201
        assert response.json()["customer_id"] == customer_id

    async def test_customer_id_in_the_body_is_ignored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Ownership comes from the token; a spoofed customer_id must not stick."""
        victim_token = await register(client)
        victim_id = (
            await client.get("/api/v1/auth/me", headers=auth_header(victim_token))
        ).json()["id"]

        attacker_token = await register(
            client, email="attacker@evil.example", organization_name="Evil"
        )
        attacker_id = (
            await client.get("/api/v1/auth/me", headers=auth_header(attacker_token))
        ).json()["id"]

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(attacker_token),
            json=widget_payload(customer_id=victim_id),
        )

        assert response.status_code == 201
        assert response.json()["customer_id"] == attacker_id
        assert response.json()["customer_id"] != victim_id

        stored = (await db_session.execute(select(Widget))).scalar_one()
        assert str(stored.customer_id) == attacker_id

    async def test_widget_id_in_the_body_is_ignored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The server assigns ids; a client-supplied one must not be honoured."""
        token = await register(client)
        forged_id = str(uuid.uuid4())

        response = await client.post(
            WIDGETS_URL, headers=auth_header(token), json=widget_payload(id=forged_id)
        )

        assert response.status_code == 201
        assert response.json()["id"] != forged_id

    async def test_widget_without_form_fields_is_allowed(
        self, client: AsyncClient
    ) -> None:
        """A cta_popover is a button, not a form."""
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(widget_type="cta_popover", form_fields=[]),
        )

        assert response.status_code == 201
        assert response.json()["form_fields"] == []

    async def test_optional_attributes_may_be_omitted(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json={
                "widget_type": "contact_form",
                "title": "Contact us",
                "form_fields": [],
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["description"] is None
        assert body["button_text"] is None
        assert body["theme_color"] is None
        assert body["is_active"] is True

    async def test_display_order_defaults_to_list_position(
        self, client: AsyncClient
    ) -> None:
        """Omitted display_order must not leave every field sharing 0."""
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(
                form_fields=[
                    {"field_name": "a", "label": "A", "field_type": "text"},
                    {"field_name": "b", "label": "B", "field_type": "text"},
                    {"field_name": "c", "label": "C", "field_type": "text"},
                ]
            ),
        )

        assert response.status_code == 201
        orders = [field["display_order"] for field in response.json()["form_fields"]]
        assert orders == [0, 1, 2]

    async def test_explicit_display_order_is_preserved(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(
                form_fields=[
                    {
                        "field_name": "a",
                        "label": "A",
                        "field_type": "text",
                        "display_order": 5,
                    },
                    {
                        "field_name": "b",
                        "label": "B",
                        "field_type": "text",
                        "display_order": 2,
                    },
                ]
            ),
        )

        assert response.status_code == 201
        orders = [field["display_order"] for field in response.json()["form_fields"]]
        assert sorted(orders) == [2, 5]

    async def test_unauthenticated_request_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(WIDGETS_URL, json=widget_payload())

        assert response.status_code == 401
        assert (await db_session.execute(select(Widget))).scalars().all() == []


class TestCreateWidgetValidation:
    @pytest.mark.parametrize(
        "widget_type",
        ["survey", "SIGNUP_FORM", "", "signup form", "cta-popover", "1"],
    )
    async def test_invalid_widget_type_is_rejected(
        self, client: AsyncClient, widget_type: str
    ) -> None:
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(widget_type=widget_type),
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "field_type",
        ["date", "EMAIL", "", "select", "file", "password"],
    )
    async def test_invalid_field_type_is_rejected(
        self, client: AsyncClient, field_type: str
    ) -> None:
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(
                form_fields=[
                    {"field_name": "x", "label": "X", "field_type": field_type}
                ]
            ),
        )

        assert response.status_code == 422

    async def test_every_valid_widget_type_is_accepted(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)

        for widget_type in ("signup_form", "contact_form", "cta_popover"):
            response = await client.post(
                WIDGETS_URL,
                headers=auth_header(token),
                json=widget_payload(widget_type=widget_type, form_fields=[]),
            )
            assert response.status_code == 201, widget_type
            assert response.json()["widget_type"] == widget_type

    async def test_every_valid_field_type_is_accepted(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)
        types = ["text", "email", "number", "textarea", "checkbox"]

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(
                form_fields=[
                    {
                        "field_name": f"field_{name}",
                        "label": name.title(),
                        "field_type": name,
                    }
                    for name in types
                ]
            ),
        )

        assert response.status_code == 201
        assert [f["field_type"] for f in response.json()["form_fields"]] == types

    async def test_a_rejected_widget_creates_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Validation runs before any write, so a 422 must leave no partial rows."""
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(
                form_fields=[
                    {"field_name": "ok", "label": "OK", "field_type": "text"},
                    {"field_name": "bad", "label": "Bad", "field_type": "nonsense"},
                ]
            ),
        )

        assert response.status_code == 422
        assert (await db_session.execute(select(Widget))).scalars().all() == []
        assert (await db_session.execute(select(FormField))).scalars().all() == []

    @pytest.mark.parametrize(
        ("label", "overrides"),
        [
            ("missing title", {"title": None}),
            ("blank title", {"title": ""}),
            ("title too long", {"title": "x" * 256}),
            ("button_text too long", {"button_text": "x" * 101}),
            ("theme_color too long", {"theme_color": "x" * 21}),
        ],
    )
    async def test_invalid_widget_attributes_are_rejected(
        self, client: AsyncClient, label: str, overrides: dict
    ) -> None:
        token = await register(client)

        response = await client.post(
            WIDGETS_URL, headers=auth_header(token), json=widget_payload(**overrides)
        )

        assert response.status_code == 422, label

    @pytest.mark.parametrize(
        ("label", "field"),
        [
            ("blank field_name", {"field_name": "", "label": "X", "field_type": "text"}),
            (
                "field_name with spaces",
                {"field_name": "first name", "label": "X", "field_type": "text"},
            ),
            (
                "field_name with symbols",
                {"field_name": "email!", "label": "X", "field_type": "text"},
            ),
            ("blank label", {"field_name": "x", "label": "", "field_type": "text"}),
            (
                "negative display_order",
                {
                    "field_name": "x",
                    "label": "X",
                    "field_type": "text",
                    "display_order": -1,
                },
            ),
        ],
    )
    async def test_invalid_form_fields_are_rejected(
        self, client: AsyncClient, label: str, field: dict
    ) -> None:
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(form_fields=[field]),
        )

        assert response.status_code == 422, label

    async def test_duplicate_field_names_are_rejected(
        self, client: AsyncClient
    ) -> None:
        """Payloads are keyed by field_name, so duplicates would collide."""
        token = await register(client)

        response = await client.post(
            WIDGETS_URL,
            headers=auth_header(token),
            json=widget_payload(
                form_fields=[
                    {"field_name": "email", "label": "Email", "field_type": "email"},
                    {"field_name": "Email", "label": "Email again", "field_type": "text"},
                ]
            ),
        )

        assert response.status_code == 422


class TestListWidgets:
    async def test_listing_returns_only_the_callers_widgets(
        self, client: AsyncClient
    ) -> None:
        """The scope is the token, not a query parameter the caller could drop."""
        token = await register(client)
        mine = [
            await create_widget(client, token, title="Mine A"),
            await create_widget(client, token, title="Mine B"),
        ]

        other_token = await register_other(client)
        theirs = await create_widget(client, other_token, title="Theirs")

        response = await client.get(WIDGETS_URL, headers=auth_header(token))

        assert response.status_code == 200
        body = response.json()
        assert {widget["id"] for widget in body} == {widget["id"] for widget in mine}
        assert theirs["id"] not in {widget["id"] for widget in body}

    async def test_listing_is_newest_first(self, client: AsyncClient) -> None:
        token = await register(client)
        await create_widget(client, token, title="Oldest")
        await create_widget(client, token, title="Newest")

        response = await client.get(WIDGETS_URL, headers=auth_header(token))

        assert response.status_code == 200
        assert [widget["title"] for widget in response.json()] == ["Newest", "Oldest"]

    async def test_listing_with_no_widgets_is_an_empty_list(
        self, client: AsyncClient
    ) -> None:
        """Absence of widgets is not an error — 200 with [], not 404."""
        token = await register(client)

        response = await client.get(WIDGETS_URL, headers=auth_header(token))

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_entries_omit_form_fields(self, client: AsyncClient) -> None:
        """The list is a summary; fields cost a query per row and go unused."""
        token = await register(client)
        await create_widget(client, token)

        response = await client.get(WIDGETS_URL, headers=auth_header(token))

        assert response.status_code == 200
        assert "form_fields" not in response.json()[0]

    async def test_unauthenticated_listing_is_rejected(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(WIDGETS_URL)

        assert response.status_code == 401


class TestRetrieveWidget:
    async def test_own_widget_is_returned_with_its_fields(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)
        created = await create_widget(client, token)

        response = await client.get(
            f"{WIDGETS_URL}/{created['id']}", headers=auth_header(token)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == created["id"]
        assert body["title"] == "Newsletter Signup"
        assert [field["field_name"] for field in body["form_fields"]] == [
            "email",
            "full_name",
        ]

    async def test_fields_come_back_in_display_order(self, client: AsyncClient) -> None:
        """Postgres returns rows unordered, so display_order must be applied."""
        token = await register(client)
        created = await create_widget(
            client,
            token,
            form_fields=[
                {
                    "field_name": "last",
                    "label": "Last",
                    "field_type": "text",
                    "display_order": 20,
                },
                {
                    "field_name": "first",
                    "label": "First",
                    "field_type": "text",
                    "display_order": 1,
                },
                {
                    "field_name": "middle",
                    "label": "Middle",
                    "field_type": "text",
                    "display_order": 10,
                },
            ],
        )

        response = await client.get(
            f"{WIDGETS_URL}/{created['id']}", headers=auth_header(token)
        )

        assert response.status_code == 200
        fields = response.json()["form_fields"]
        assert [field["field_name"] for field in fields] == ["first", "middle", "last"]
        assert [field["display_order"] for field in fields] == [1, 10, 20]

    async def test_another_customers_widget_is_404_not_403(
        self, client: AsyncClient
    ) -> None:
        """403 would confirm the id exists — an oracle across tenants (FR1.4)."""
        owner_token = await register(client)
        widget = await create_widget(client, owner_token)

        intruder_token = await register_other(client)

        response = await client.get(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(intruder_token)
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Widget not found"

    async def test_unknown_id_is_indistinguishable_from_someone_elses(
        self, client: AsyncClient
    ) -> None:
        """Same status and same body, or the difference itself leaks existence."""
        owner_token = await register(client)
        widget = await create_widget(client, owner_token)
        intruder_token = await register_other(client)

        cross_tenant = await client.get(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(intruder_token)
        )
        nonexistent = await client.get(
            f"{WIDGETS_URL}/{uuid.uuid4()}", headers=auth_header(intruder_token)
        )

        assert cross_tenant.status_code == nonexistent.status_code == 404
        assert cross_tenant.json() == nonexistent.json()

    async def test_malformed_id_is_rejected(self, client: AsyncClient) -> None:
        token = await register(client)

        response = await client.get(
            f"{WIDGETS_URL}/not-a-uuid", headers=auth_header(token)
        )

        assert response.status_code == 422

    async def test_unauthenticated_retrieval_is_rejected(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.get(f"{WIDGETS_URL}/{widget['id']}")

        assert response.status_code == 401
