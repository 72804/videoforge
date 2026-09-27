# ruff: noqa: E501
"""Add friend-group social, visibility, voices, series.

Do not apply to production Neon in Phase 17.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260927_0004"
down_revision = "20260920_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def has_col(table: str, name: str) -> bool:
        return name in {c["name"] for c in inspector.get_columns(table)}

    def add(table: str, column: sa.Column) -> None:
        if has_col(table, column.name):
            return
        op.add_column(table, column)

    names = set(inspector.get_table_names())

    add("telegram_users", sa.Column("display_name", sa.Text(), nullable=False, server_default=""))
    add("telegram_users", sa.Column("bio", sa.Text(), nullable=False, server_default=""))
    add("telegram_users", sa.Column("avatar_storage_key", sa.Text(), nullable=True))
    add(
        "telegram_users",
        sa.Column("default_traits", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    add(
        "telegram_users",
        sa.Column("allow_friends_to_cast_me", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add("projects", sa.Column("visibility", sa.Text(), nullable=False, server_default="PRIVATE"))
    add("projects", sa.Column("series_id", sa.String(length=36), nullable=True))
    add("projects", sa.Column("episode_number", sa.Integer(), nullable=True))
    add("characters", sa.Column("persona", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    add(
        "script_versions",
        sa.Column("story_spec", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    add(
        "scene_versions",
        sa.Column("dialogue_lines", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    add(
        "scene_versions",
        sa.Column(
            "supplied_reference_keys",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    add("renders", sa.Column("burn_subtitles", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "voice_profiles" not in names:
        op.create_table(
            "voice_profiles",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("owner_user_id", sa.String(length=36), nullable=True),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("voice_id", sa.Text(), nullable=False),
            sa.Column("display_name", sa.Text(), nullable=False),
            sa.Column("language", sa.Text(), nullable=False, server_default="en"),
            sa.Column("style", sa.Text(), nullable=False, server_default=""),
            sa.Column("emotion_defaults", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "friendships" not in names:
        op.create_table(
            "friendships",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("requester_id", sa.String(length=36), sa.ForeignKey("telegram_users.id"), nullable=False),
            sa.Column("addressee_id", sa.String(length=36), sa.ForeignKey("telegram_users.id"), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("requester_id", "addressee_id", name="friendships_pair_key"),
        )
    if "personas" not in names:
        op.create_table(
            "personas",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("telegram_users.id"), nullable=False),
            sa.Column("payload", JSONB(), nullable=False),
        )
    if "persona_references" not in names:
        op.create_table(
            "persona_references",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("persona_id", sa.String(length=36), sa.ForeignKey("personas.id"), nullable=False),
            sa.Column("storage_key", sa.Text(), nullable=False),
            sa.Column("sha256", sa.Text(), nullable=False, server_default=""),
            sa.Column("external_path", sa.Text(), nullable=False, server_default=""),
            sa.Column("primary_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "series" not in names:
        op.create_table(
            "series",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("telegram_users.id"), nullable=False),
            sa.Column("slug", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "series_continuity" not in names:
        op.create_table(
            "series_continuity",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("series_id", sa.String(length=36), sa.ForeignKey("series.id"), nullable=False),
            sa.Column("previous_event_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("running_jokes", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("unresolved_conflicts", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("character_notes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("last_episode_project_id", sa.String(length=36), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "dialogue_tracks" not in names:
        op.create_table(
            "dialogue_tracks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("payload", JSONB(), nullable=False),
        )
    if "audio_mixes" not in names:
        op.create_table(
            "audio_mixes",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("payload", JSONB(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    names = set(inspector.get_table_names())
    for table in (
        "audio_mixes",
        "dialogue_tracks",
        "series_continuity",
        "series",
        "persona_references",
        "personas",
        "friendships",
        "voice_profiles",
    ):
        if table in names:
            op.drop_table(table)
    def drop_col(table: str, name: str) -> None:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if name in existing:
            op.drop_column(table, name)

    drop_col("renders", "burn_subtitles")
    drop_col("scene_versions", "supplied_reference_keys")
    drop_col("scene_versions", "dialogue_lines")
    drop_col("script_versions", "story_spec")
    drop_col("characters", "persona")
    drop_col("projects", "episode_number")
    drop_col("projects", "series_id")
    drop_col("projects", "visibility")
    drop_col("telegram_users", "allow_friends_to_cast_me")
    drop_col("telegram_users", "default_traits")
    drop_col("telegram_users", "avatar_storage_key")
    drop_col("telegram_users", "bio")
    drop_col("telegram_users", "display_name")
