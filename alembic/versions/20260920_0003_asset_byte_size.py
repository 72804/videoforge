"""Add asset_versions.byte_size for object-storage metadata."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260920_0003"
down_revision = "20260920_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("asset_versions")}
    if "byte_size" not in columns:
        op.add_column(
            "asset_versions",
            sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        )
    render_cols = {col["name"] for col in inspector.get_columns("renders")}
    if "asset_version_id" not in render_cols:
        op.add_column("renders", sa.Column("asset_version_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column("renders", "asset_version_id")
    op.drop_column("asset_versions", "byte_size")
