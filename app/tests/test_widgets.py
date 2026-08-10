"""Tests for widget creation, listing, retrieval, update, deletion and embeds.

Ownership is the property under test throughout: a widget belongs to the caller
identified by the access token, nothing in the request body can change that, and
another tenant's widget is indistinguishable from one that does not exist.
"""

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.models.form_field import FormField
from app.models.submission import Submission
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


class TestUpdateWidget:
    async def test_attributes_are_updated(self, client: AsyncClient) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={"title": "Renamed", "theme_color": "#ff0000"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "Renamed"
        assert body["theme_color"] == "#ff0000"

    async def test_omitted_attributes_are_left_alone(
        self, client: AsyncClient
    ) -> None:
        """PATCH, not PUT: unsent keys must not be reset to their defaults."""
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={"title": "Renamed"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["description"] == "Join our list"
        assert body["button_text"] == "Subscribe"
        assert body["theme_color"] == "#3366ff"
        assert body["widget_type"] == "signup_form"

    async def test_nullable_attributes_can_be_cleared(
        self, client: AsyncClient
    ) -> None:
        """An explicit null on a nullable column means "clear it", not "ignore"."""
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={"description": None, "button_text": None},
        )

        assert response.status_code == 200
        assert response.json()["description"] is None
        assert response.json()["button_text"] is None

    async def test_fields_are_fully_replaced(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The sent set becomes the whole set — old rows go, new rows arrive."""
        token = await register(client)
        widget = await create_widget(client, token)
        original_field_ids = {field["id"] for field in widget["form_fields"]}

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={
                "form_fields": [
                    {
                        "field_name": "company",
                        "label": "Company",
                        "field_type": "text",
                        "display_order": 0,
                    },
                ]
            },
        )

        assert response.status_code == 200
        fields = response.json()["form_fields"]
        assert [field["field_name"] for field in fields] == ["company"]
        # New rows, not edited ones: replacement means the old ids are gone.
        assert original_field_ids.isdisjoint({field["id"] for field in fields})

        stored = (await db_session.execute(select(FormField))).scalars().all()
        assert len(stored) == 1
        assert stored[0].field_name == "company"

    async def test_replacing_fields_keeps_them_ordered(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={
                "form_fields": [
                    {
                        "field_name": "third",
                        "label": "Third",
                        "field_type": "text",
                        "display_order": 30,
                    },
                    {
                        "field_name": "first",
                        "label": "First",
                        "field_type": "text",
                        "display_order": 10,
                    },
                ]
            },
        )

        assert response.status_code == 200
        fields = response.json()["form_fields"]
        assert [field["field_name"] for field in fields] == ["first", "third"]

    async def test_empty_field_list_clears_the_form(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """[] is a real instruction — a signup form becoming a bare CTA."""
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={"widget_type": "cta_popover", "form_fields": []},
        )

        assert response.status_code == 200
        assert response.json()["form_fields"] == []
        assert (await db_session.execute(select(FormField))).scalars().all() == []

    async def test_omitting_form_fields_leaves_them_untouched(
        self, client: AsyncClient
    ) -> None:
        """Absent is not the same as []: only one of them wipes the form."""
        token = await register(client)
        widget = await create_widget(client, token)
        original_field_ids = {field["id"] for field in widget["form_fields"]}

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={"title": "Renamed"},
        )

        assert response.status_code == 200
        fields = response.json()["form_fields"]
        assert {field["id"] for field in fields} == original_field_ids

    async def test_ownership_cannot_be_reassigned(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """customer_id is not on WidgetUpdate, so sending it changes nothing."""
        token = await register(client)
        widget = await create_widget(client, token)
        rival_token = await register_other(client)
        rival_id = (
            await client.get("/api/v1/auth/me", headers=auth_header(rival_token))
        ).json()["id"]

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={"title": "Renamed", "customer_id": rival_id},
        )

        assert response.status_code == 200
        assert response.json()["customer_id"] == widget["customer_id"]

    async def test_cross_tenant_update_is_404(self, client: AsyncClient) -> None:
        owner_token = await register(client)
        widget = await create_widget(client, owner_token)
        intruder_token = await register_other(client)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(intruder_token),
            json={"title": "Hijacked"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Widget not found"

    async def test_a_rejected_cross_tenant_update_changes_nothing(
        self, client: AsyncClient
    ) -> None:
        owner_token = await register(client)
        widget = await create_widget(client, owner_token)
        intruder_token = await register_other(client)

        await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(intruder_token),
            json={"title": "Hijacked", "form_fields": []},
        )

        after = await client.get(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(owner_token)
        )
        assert after.json()["title"] == "Newsletter Signup"
        assert len(after.json()["form_fields"]) == 2

    @pytest.mark.parametrize(
        ("label", "body"),
        [
            ("empty body", {}),
            ("unknown key only", {"widgetType": "contact_form"}),
            ("null title", {"title": None}),
            ("blank title", {"title": ""}),
            ("invalid widget_type", {"widget_type": "survey"}),
            (
                "invalid field_type",
                {
                    "form_fields": [
                        {"field_name": "x", "label": "X", "field_type": "date"}
                    ]
                },
            ),
            (
                "duplicate field names",
                {
                    "form_fields": [
                        {"field_name": "email", "label": "A", "field_type": "email"},
                        {"field_name": "Email", "label": "B", "field_type": "text"},
                    ]
                },
            ),
        ],
    )
    async def test_invalid_updates_are_rejected(
        self, client: AsyncClient, label: str, body: dict
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token), json=body
        )

        assert response.status_code == 422, label

    async def test_a_rejected_update_leaves_fields_intact(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Validation runs before the delete, so a 422 must not wipe the form."""
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={
                "form_fields": [
                    {"field_name": "ok", "label": "OK", "field_type": "text"},
                    {"field_name": "bad", "label": "Bad", "field_type": "nonsense"},
                ]
            },
        )

        assert response.status_code == 422
        stored = (await db_session.execute(select(FormField))).scalars().all()
        assert len(stored) == 2

    async def test_unauthenticated_update_is_rejected(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.patch(
            f"{WIDGETS_URL}/{widget['id']}", json={"title": "Renamed"}
        )

        assert response.status_code == 401


class TestDeleteWidget:
    async def test_widget_is_deleted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.delete(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token)
        )

        assert response.status_code == 204
        assert (await db_session.execute(select(Widget))).scalars().all() == []

        follow_up = await client.get(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token)
        )
        assert follow_up.status_code == 404

    async def test_form_fields_are_cascade_deleted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.delete(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token)
        )

        assert response.status_code == 204
        assert (await db_session.execute(select(FormField))).scalars().all() == []

    async def test_submissions_survive_with_a_null_widget_id(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A captured lead outlives the form it arrived through (ON DELETE SET NULL)."""
        token = await register(client)
        widget = await create_widget(client, token)
        customer_id = uuid.UUID(widget["customer_id"])

        submission = Submission(
            widget_id=uuid.UUID(widget["id"]),
            customer_id=customer_id,
            payload={"email": "lead@example.com"},
        )
        db_session.add(submission)
        await db_session.commit()

        response = await client.delete(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token)
        )

        assert response.status_code == 204

        db_session.expire_all()
        survivors = (await db_session.execute(select(Submission))).scalars().all()
        assert len(survivors) == 1
        assert survivors[0].widget_id is None
        # The data itself is the point of keeping the row, not just the row.
        assert survivors[0].payload == {"email": "lead@example.com"}
        assert survivors[0].customer_id == customer_id

    async def test_cross_tenant_delete_is_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner_token = await register(client)
        widget = await create_widget(client, owner_token)
        intruder_token = await register_other(client)

        response = await client.delete(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(intruder_token)
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Widget not found"
        assert len((await db_session.execute(select(Widget))).scalars().all()) == 1

    async def test_deleting_one_widget_leaves_the_others(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)
        doomed = await create_widget(client, token, title="Doomed")
        kept = await create_widget(client, token, title="Kept")

        response = await client.delete(
            f"{WIDGETS_URL}/{doomed['id']}", headers=auth_header(token)
        )

        assert response.status_code == 204
        listing = await client.get(WIDGETS_URL, headers=auth_header(token))
        assert [widget["id"] for widget in listing.json()] == [kept["id"]]

    async def test_deleting_an_unknown_id_is_404(self, client: AsyncClient) -> None:
        token = await register(client)

        response = await client.delete(
            f"{WIDGETS_URL}/{uuid.uuid4()}", headers=auth_header(token)
        )

        assert response.status_code == 404

    async def test_unauthenticated_delete_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.delete(f"{WIDGETS_URL}/{widget['id']}")

        assert response.status_code == 401
        assert len((await db_session.execute(select(Widget))).scalars().all()) == 1


class TestEmbedSnippet:
    async def test_snippet_is_present_on_the_detail_response(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.get(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token)
        )

        assert response.status_code == 200
        assert response.json()["embed_snippet"] == (
            f'<script src="{settings.WIDGET_EMBED_BASE_URL}'
            f'/widget.js?id={widget["id"]}"></script>'
        )

    async def test_the_snippet_carries_this_widgets_id(
        self, client: AsyncClient
    ) -> None:
        """The id in the snippet must be the id of the widget being fetched."""
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.get(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token)
        )

        snippet = response.json()["embed_snippet"]
        assert widget["id"] in snippet

    async def test_the_snippet_survives_a_field_replacement(
        self, client: AsyncClient
    ) -> None:
        """The snippet is keyed by id, so editing fields must not change it."""
        token = await register(client)
        widget = await create_widget(client, token)

        await client.patch(
            f"{WIDGETS_URL}/{widget['id']}",
            headers=auth_header(token),
            json={"form_fields": []},
        )
        response = await client.get(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token)
        )

        assert response.json()["embed_snippet"] == (
            f'<script src="{settings.WIDGET_EMBED_BASE_URL}'
            f'/widget.js?id={widget["id"]}"></script>'
        )

    async def test_the_list_response_has_no_snippet(self, client: AsyncClient) -> None:
        """The snippet only makes sense for one widget, so the list omits it."""
        token = await register(client)
        await create_widget(client, token)

        response = await client.get(WIDGETS_URL, headers=auth_header(token))

        assert response.status_code == 200
        assert "embed_snippet" not in response.json()[0]

    async def test_the_snippet_matches_the_documented_shape(
        self, client: AsyncClient
    ) -> None:
        """Pins the literal format, not just the interpolation of it."""
        token = await register(client)
        widget = await create_widget(client, token)

        response = await client.get(
            f"{WIDGETS_URL}/{widget['id']}", headers=auth_header(token)
        )

        assert re.fullmatch(
            r'<script src="https://[^"?\s]+/widget\.js\?id='
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}">'
            r"</script>",
            response.json()["embed_snippet"],
        )

    def test_a_trailing_slash_on_the_base_url_is_normalised(self) -> None:
        """Or the snippet would carry "//widget.js" for a URL set with a slash."""
        assert (
            Settings(WIDGET_EMBED_BASE_URL="https://cdn.example.com/").WIDGET_EMBED_BASE_URL
            == "https://cdn.example.com"
        )
