"""Add payment intents and refund_status."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260920_0002"
down_revision = "20260920_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "payment_intents" not in tables:
        op.create_table(
            "payment_intents",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("telegram_users.id"),
                nullable=False,
            ),
            sa.Column(
                "quote_id",
                sa.String(length=36),
                sa.ForeignKey("star_quotes.id"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("projects.id"),
                nullable=False,
            ),
            sa.Column("plan_hash", sa.Text(), nullable=False),
            sa.Column("stars", sa.Integer(), nullable=False),
            sa.Column("invoice_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("telegram_payment_charge_id", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("payment_intents_quote_idx", "payment_intents", ["quote_id"])
    payment_cols = {col["name"] for col in inspector.get_columns("telegram_payments")}
    if "refund_status" not in payment_cols:
        op.add_column(
            "telegram_payments",
            sa.Column("refund_status", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    payment_cols = {col["name"] for col in inspector.get_columns("telegram_payments")}
    if "refund_status" in payment_cols:
        op.drop_column("telegram_payments", "refund_status")
    if "payment_intents" in inspector.get_table_names():
        op.drop_index("payment_intents_quote_idx", table_name="payment_intents")
        op.drop_table("payment_intents")
