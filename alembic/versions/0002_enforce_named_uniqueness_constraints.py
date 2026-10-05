"""enforce named uniqueness constraints

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02 23:27:46.298254
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_orders_number"), table_name="orders")
    op.create_unique_constraint(op.f("uq_orders_number"), "orders", ["number"])
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.create_unique_constraint(op.f("uq_users_email"), "users", ["email"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_users_email"), "users", type_="unique")
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.drop_constraint(op.f("uq_orders_number"), "orders", type_="unique")
    op.create_index(op.f("ix_orders_number"), "orders", ["number"], unique=True)
