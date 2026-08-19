"""Tests for the owner dashboard: listing submissions and analytics.

Ownership is the property under test throughout, as in test_widgets.py: the scope
of a dashboard query is the token, a widget_id filter must reference a widget the
caller owns (or produce the same 404 a missing widget does), and no other
tenant's submissions can ever appear.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import Submission

SIGNUP_URL = "/api/v1/auth/signup"
WIDGETS_URL = "/api/v1/widgets"
DASHBOARD_SUBMISSIONS_URL = "/api/v1/dashboard/submissions"
DASHBOARD_ANALYTICS_URL = "/api/v1/dashboard/analytics"

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
        "form_fields": [],
    }
    payload.update(overrides)
    return payload


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client: AsyncClient, **overrides) -> str:
    response = await client.post(SIGNUP_URL, json=signup_payload(**overrides))
    assert response.status_code == 201
    return response.json()["access_token"]


async def register_other(client: AsyncClient) -> str:
    return await register(
        client, email="rival@other.example", organization_name="Other Co"
    )


async def create_widget(client: AsyncClient, token: str, **overrides) -> dict:
    response = await client.post(
        WIDGETS_URL, headers=auth_header(token), json=widget_payload(**overrides)
    )
    assert response.status_code == 201
    return response.json()


async def add_submission(
    db: AsyncSession,
    *,
    widget_id: uuid.UUID | None,
    customer_id: uuid.UUID,
    payload: dict | None = None,
    geo_country: str | None = None,
    is_spam: bool = False,
    created_at: datetime | None = None,
) -> Submission:
    submission = Submission(
        widget_id=widget_id,
        customer_id=customer_id,
        payload=payload or {"email": "visitor@example.com"},
        geo_country=geo_country,
        is_spam=is_spam,
    )
    if created_at is not None:
        submission.created_at = created_at
    db.add(submission)
    await db.flush()
    return submission


class TestListSubmissions:
    async def test_unauthenticated_request_is_rejected(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(DASHBOARD_SUBMISSIONS_URL)

        assert response.status_code == 401

    async def test_empty_customer_gets_an_empty_page(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)

        response = await client.get(
            DASHBOARD_SUBMISSIONS_URL, headers=auth_header(token)
        )

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}

    async def test_listing_returns_only_the_callers_submissions(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        mine = await create_widget(client, token, title="Mine")
        customer_id = uuid.UUID(mine["customer_id"])
        await add_submission(
            db_session,
            widget_id=uuid.UUID(mine["id"]),
            customer_id=customer_id,
            payload={"email": "mine@example.com"},
        )

        other_token = await register_other(client)
        theirs = await create_widget(client, other_token, title="Theirs")
        await add_submission(
            db_session,
            widget_id=uuid.UUID(theirs["id"]),
            customer_id=uuid.UUID(theirs["customer_id"]),
            payload={"email": "theirs@example.com"},
        )
        await db_session.commit()

        response = await client.get(
            DASHBOARD_SUBMISSIONS_URL, headers=auth_header(token)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["payload"] == {"email": "mine@example.com"}

    async def test_listing_is_newest_first(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)
        customer_id = uuid.UUID(widget["customer_id"])
        widget_id = uuid.UUID(widget["id"])
        await add_submission(
            db_session,
            widget_id=widget_id,
            customer_id=customer_id,
            payload={"order": "older"},
            created_at=datetime.now() - timedelta(days=2),
        )
        await add_submission(
            db_session,
            widget_id=widget_id,
            customer_id=customer_id,
            payload={"order": "newer"},
            created_at=datetime.now(),
        )
        await db_session.commit()

        response = await client.get(
            DASHBOARD_SUBMISSIONS_URL, headers=auth_header(token)
        )

        assert response.status_code == 200
        assert [item["payload"]["order"] for item in response.json()["items"]] == [
            "newer",
            "older",
        ]

    async def test_widget_filter_restricts_the_page(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget_a = await create_widget(client, token, title="A")
        widget_b = await create_widget(client, token, title="B")
        customer_id = uuid.UUID(widget_a["customer_id"])
        await add_submission(
            db_session,
            widget_id=uuid.UUID(widget_a["id"]),
            customer_id=customer_id,
        )
        await add_submission(
            db_session,
            widget_id=uuid.UUID(widget_b["id"]),
            customer_id=customer_id,
        )
        await db_session.commit()

        response = await client.get(
            DASHBOARD_SUBMISSIONS_URL,
            headers=auth_header(token),
            params={"widget_id": widget_a["id"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["widget_id"] == widget_a["id"]
        assert body["items"][0]["widget_title"] == "A"

    async def test_cross_tenant_widget_filter_is_404(
        self, client: AsyncClient
    ) -> None:
        """Filtering by someone else's widget must not confirm it exists."""
        owner_token = await register(client)
        widget = await create_widget(client, owner_token)
        intruder_token = await register_other(client)

        response = await client.get(
            DASHBOARD_SUBMISSIONS_URL,
            headers=auth_header(intruder_token),
            params={"widget_id": widget["id"]},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Widget not found"

    async def test_unknown_widget_filter_is_404(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)

        response = await client.get(
            DASHBOARD_SUBMISSIONS_URL,
            headers=auth_header(token),
            params={"widget_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404

    async def test_pagination_slices_the_page(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)
        customer_id = uuid.UUID(widget["customer_id"])
        widget_id = uuid.UUID(widget["id"])
        for i in range(5):
            await add_submission(
                db_session,
                widget_id=widget_id,
                customer_id=customer_id,
                payload={"n": str(i)},
            )
        await db_session.commit()

        page = await client.get(
            DASHBOARD_SUBMISSIONS_URL,
            headers=auth_header(token),
            params={"limit": 2, "offset": 2},
        )

        assert page.status_code == 200
        body = page.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 2

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
    async def test_invalid_pagination_is_rejected(
        self, client: AsyncClient, params: dict
    ) -> None:
        token = await register(client)

        response = await client.get(
            DASHBOARD_SUBMISSIONS_URL,
            headers=auth_header(token),
            params=params,
        )

        assert response.status_code == 422

    async def test_submission_from_a_deleted_widget_still_appears(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """ON DELETE SET NULL keeps the lead; the title is simply unknown."""
        token = await register(client)
        widget = await create_widget(client, token)
        customer_id = uuid.UUID(widget["customer_id"])
        submission = await add_submission(
            db_session,
            widget_id=uuid.UUID(widget["id"]),
            customer_id=customer_id,
            payload={"email": "orphan@example.com"},
        )
        await db_session.commit()
        submission.widget_id = None
        await db_session.commit()

        response = await client.get(
            DASHBOARD_SUBMISSIONS_URL, headers=auth_header(token)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["widget_id"] is None
        assert item["widget_title"] is None


class TestAnalytics:
    async def test_unauthenticated_request_is_rejected(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(DASHBOARD_ANALYTICS_URL)

        assert response.status_code == 401

    async def test_empty_customer_gets_zeroed_analytics(
        self, client: AsyncClient
    ) -> None:
        token = await register(client)

        response = await client.get(DASHBOARD_ANALYTICS_URL, headers=auth_header(token))

        assert response.status_code == 200
        assert response.json() == {
            "total": 0,
            "by_widget": {},
            "by_country": {},
            "by_spam": [],
            "over_time": [],
        }

    async def test_analytics_aggregates_by_widget_country_and_spam(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget_a = await create_widget(client, token, title="A")
        widget_b = await create_widget(client, token, title="B")
        customer_id = uuid.UUID(widget_a["customer_id"])
        widget_a_id = uuid.UUID(widget_a["id"])
        widget_b_id = uuid.UUID(widget_b["id"])

        await add_submission(
            db_session,
            widget_id=widget_a_id,
            customer_id=customer_id,
            geo_country="US",
        )
        await add_submission(
            db_session,
            widget_id=widget_a_id,
            customer_id=customer_id,
            geo_country="US",
        )
        await add_submission(
            db_session,
            widget_id=widget_b_id,
            customer_id=customer_id,
            geo_country="CA",
        )
        await add_submission(
            db_session,
            widget_id=widget_b_id,
            customer_id=customer_id,
            geo_country=None,
            is_spam=True,
        )
        await db_session.commit()

        response = await client.get(DASHBOARD_ANALYTICS_URL, headers=auth_header(token))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4
        assert body["by_widget"] == {
            widget_a["id"]: 2,
            widget_b["id"]: 2,
        }
        assert body["by_country"] == {"US": 2, "CA": 1, "unknown": 1}
        by_spam = {entry["is_spam"]: entry["count"] for entry in body["by_spam"]}
        assert by_spam == {False: 3, True: 1}

    async def test_analytics_only_sees_the_callers_submissions(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)
        await add_submission(
            db_session,
            widget_id=uuid.UUID(widget["id"]),
            customer_id=uuid.UUID(widget["customer_id"]),
            geo_country="US",
        )

        other_token = await register_other(client)
        their_widget = await create_widget(client, other_token, title="Theirs")
        await add_submission(
            db_session,
            widget_id=uuid.UUID(their_widget["id"]),
            customer_id=uuid.UUID(their_widget["customer_id"]),
            geo_country="US",
        )
        await db_session.commit()

        response = await client.get(DASHBOARD_ANALYTICS_URL, headers=auth_header(token))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["by_country"] == {"US": 1}

    async def test_analytics_counts_over_time_by_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget = await create_widget(client, token)
        customer_id = uuid.UUID(widget["customer_id"])
        widget_id = uuid.UUID(widget["id"])

        await add_submission(
            db_session,
            widget_id=widget_id,
            customer_id=customer_id,
            created_at=datetime.now() - timedelta(days=2),
        )
        await add_submission(
            db_session,
            widget_id=widget_id,
            customer_id=customer_id,
            created_at=datetime.now() - timedelta(days=2),
        )
        await add_submission(
            db_session,
            widget_id=widget_id,
            customer_id=customer_id,
            created_at=datetime.now(),
        )
        await db_session.commit()

        response = await client.get(DASHBOARD_ANALYTICS_URL, headers=auth_header(token))

        assert response.status_code == 200
        over_time = response.json()["over_time"]
        assert [entry["count"] for entry in over_time] == [2, 1]

    async def test_widget_filter_scopes_the_analytics(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await register(client)
        widget_a = await create_widget(client, token, title="A")
        widget_b = await create_widget(client, token, title="B")
        customer_id = uuid.UUID(widget_a["customer_id"])
        await add_submission(
            db_session,
            widget_id=uuid.UUID(widget_a["id"]),
            customer_id=customer_id,
            geo_country="US",
        )
        await add_submission(
            db_session,
            widget_id=uuid.UUID(widget_b["id"]),
            customer_id=customer_id,
            geo_country="CA",
        )
        await db_session.commit()

        response = await client.get(
            DASHBOARD_ANALYTICS_URL,
            headers=auth_header(token),
            params={"widget_id": widget_a["id"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["by_widget"] == {widget_a["id"]: 1}
        assert body["by_country"] == {"US": 1}

    async def test_cross_tenant_widget_filter_is_404(
        self, client: AsyncClient
    ) -> None:
        owner_token = await register(client)
        widget = await create_widget(client, owner_token)
        intruder_token = await register_other(client)

        response = await client.get(
            DASHBOARD_ANALYTICS_URL,
            headers=auth_header(intruder_token),
            params={"widget_id": widget["id"]},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Widget not found"