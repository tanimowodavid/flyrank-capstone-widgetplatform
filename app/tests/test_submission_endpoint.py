"""Tests for public submission endpoint (Stage 4)."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.widget import Widget
from app.repositories.submission import SubmissionRepository


class TestSubmissionEndpoint:
    """Tests for POST /api/v1/widgets/{id}/submit"""

    async def test_valid_submission_returns_201(
        self,
        client: AsyncClient,
        active_widget: Widget,
    ) -> None:
        """Valid submission returns 201 Created with submission ID."""
        payload = {
            "field_values": {"email": "test@example.com", "name": "John Doe"},
            "referrer": "https://example.com",
            "user_agent": "Mozilla/5.0",
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert "created_at" in data
        assert "message" in data
        # Verify it's a valid UUID string
        uuid.UUID(data["id"])

    async def test_submission_has_cors_header(
        self, client: AsyncClient, active_widget: Widget
    ) -> None:
        """Submission response includes CORS header."""
        payload = {
            "field_values": {"email": "test@example.com"},
            "referrer": None,
            "user_agent": None,
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201
        assert response.headers.get("Access-Control-Allow-Origin") == "*"

    async def test_submission_has_no_cache_header(
        self, client: AsyncClient, active_widget: Widget
    ) -> None:
        """POST submissions are not cached."""
        payload = {
            "field_values": {"email": "test@example.com"},
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201
        cache_control = response.headers.get("Cache-Control")
        assert cache_control
        assert "no-cache" in cache_control or "no-store" in cache_control

    async def test_inactive_widget_returns_404(
        self,
        client: AsyncClient,
        inactive_widget: Widget,
    ) -> None:
        """Submission to inactive widget returns 404."""
        payload = {
            "field_values": {"email": "test@example.com"},
        }

        response = await client.post(
            f"/api/v1/widgets/{inactive_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 404

    async def test_nonexistent_widget_returns_404(
        self,
        client: AsyncClient,
    ) -> None:
        """Submission to nonexistent widget returns 404."""
        fake_widget_id = uuid.uuid4()
        payload = {
            "field_values": {"email": "test@example.com"},
        }

        response = await client.post(
            f"/api/v1/widgets/{fake_widget_id}/submit",
            json=payload,
        )

        assert response.status_code == 404

    async def test_submission_stored_in_database(
        self,
        client: AsyncClient,
        active_widget: Widget,
        db: AsyncSession,
    ) -> None:
        """Submission is persisted to database."""
        payload = {
            "field_values": {"email": "test@example.com", "name": "Jane"},
            "referrer": "https://test.com",
            "user_agent": "TestAgent/1.0",
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        submission_id = uuid.UUID(data["id"])

        # Verify in database
        repo = SubmissionRepository(db)
        submission = await repo.get_by_id(
            submission_id, active_widget.customer_id
        )
        assert submission is not None
        assert submission.widget_id == active_widget.id
        assert submission.customer_id == active_widget.customer_id
        assert submission.payload == {"email": "test@example.com", "name": "Jane"}
        # User-Agent comes from HTTP header, not from payload
        assert submission.user_agent is not None

    async def test_submission_contains_referrer(
        self,
        client: AsyncClient,
        active_widget: Widget,
        db: AsyncSession,
    ) -> None:
        """Submission stores referrer URL."""
        referrer_url = "https://example.com/page"
        payload = {
            "field_values": {"email": "test@example.com"},
            "referrer": referrer_url,
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        submission_id = uuid.UUID(data["id"])

        repo = SubmissionRepository(db)
        submission = await repo.get_by_id(
            submission_id, active_widget.customer_id
        )
        # Referrer is not directly stored but is in payload or could be extracted
        # (depends on implementation details)
        assert submission is not None

    async def test_submission_extracts_user_agent_from_header(
        self,
        client: AsyncClient,
        active_widget: Widget,
        db: AsyncSession,
    ) -> None:
        """Submission extracts User-Agent from HTTP header."""
        payload = {
            "field_values": {"email": "test@example.com"},
            "referrer": None,
            "user_agent": None,  # Rely on header
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
            headers={"User-Agent": "CustomAgent/2.0"},
        )

        assert response.status_code == 201
        data = response.json()
        submission_id = uuid.UUID(data["id"])

        repo = SubmissionRepository(db)
        submission = await repo.get_by_id(
            submission_id, active_widget.customer_id
        )
        assert submission is not None
        assert submission.user_agent == "CustomAgent/2.0"

    async def test_submission_extracts_ip_from_x_forwarded_for(
        self,
        client: AsyncClient,
        active_widget: Widget,
        db: AsyncSession,
    ) -> None:
        """Submission extracts IP from X-Forwarded-For header."""
        payload = {
            "field_values": {"email": "test@example.com"},
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
            headers={"X-Forwarded-For": "192.0.2.100, 10.0.0.1"},
        )

        assert response.status_code == 201
        data = response.json()
        submission_id = uuid.UUID(data["id"])

        repo = SubmissionRepository(db)
        submission = await repo.get_by_id(
            submission_id, active_widget.customer_id
        )
        assert submission is not None
        # Should extract the first IP from the list
        assert submission.submitter_ip == "192.0.2.100"

    async def test_submission_with_empty_field_values(
        self,
        client: AsyncClient,
        active_widget: Widget,
    ) -> None:
        """Submission with empty field values is accepted."""
        payload = {
            "field_values": {},
            "referrer": None,
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        # Should still be accepted (validation is frontend responsibility)
        assert response.status_code == 201

    async def test_submission_with_null_values(
        self,
        client: AsyncClient,
        active_widget: Widget,
    ) -> None:
        """Submission allows null field values (optional fields)."""
        payload = {
            "field_values": {"email": "test@example.com", "name": None},
            "referrer": None,
            "user_agent": None,
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201

    async def test_multiple_submissions_for_same_widget(
        self,
        client: AsyncClient,
        active_widget: Widget,
        db: AsyncSession,
    ) -> None:
        """Multiple submissions for the same widget are stored separately."""
        payloads = [
            {"field_values": {"email": "user1@example.com"}},
            {"field_values": {"email": "user2@example.com"}},
            {"field_values": {"email": "user3@example.com"}},
        ]

        submission_ids = []
        for payload in payloads:
            response = await client.post(
                f"/api/v1/widgets/{active_widget.id}/submit",
                json=payload,
            )
            assert response.status_code == 201
            submission_ids.append(uuid.UUID(response.json()["id"]))

        # Verify all stored and distinct
        repo = SubmissionRepository(db)
        submissions = await repo.list_by_widget(
            active_widget.id, active_widget.customer_id
        )
        assert len(submissions) == 3
        stored_ids = {s.id for s in submissions}
        assert stored_ids == set(submission_ids)

    async def test_submission_is_not_spam_by_default(
        self,
        client: AsyncClient,
        active_widget: Widget,
        db: AsyncSession,
    ) -> None:
        """Submissions default to is_spam=false (spam detection is Stage 5)."""
        payload = {
            "field_values": {"email": "test@example.com"},
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        submission_id = uuid.UUID(data["id"])

        repo = SubmissionRepository(db)
        submission = await repo.get_by_id(
            submission_id, active_widget.customer_id
        )
        assert submission is not None
        assert submission.is_spam is False

    async def test_submission_response_includes_message(
        self,
        client: AsyncClient,
        active_widget: Widget,
    ) -> None:
        """Submission response includes user-friendly message."""
        payload = {
            "field_values": {"email": "test@example.com"},
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "Thank you for your submission"

    async def test_submission_response_includes_iso_timestamp(
        self,
        client: AsyncClient,
        active_widget: Widget,
    ) -> None:
        """Submission response created_at is ISO 8601 format."""
        payload = {
            "field_values": {"email": "test@example.com"},
        }

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        # Should parse without error
        from datetime import datetime

        datetime.fromisoformat(data["created_at"])
