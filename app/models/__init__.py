"""ORM model registry.

Every model module must be imported here. Alembic autogenerate only sees tables
that have been registered on Base.metadata by an actual import — a model that is
never imported is silently missing from migrations.

Imports Base from app.db.base (not app.db) so that importing metadata does not
also build the engine.
"""

from app.db.base import Base

__all__ = ["Base"]
