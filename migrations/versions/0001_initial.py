"""Initial profiles and lift results."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("nickname", sa.String(64), nullable=False),
        sa.Column("sex", sa.String(10), nullable=False),
        sa.Column("bodyweight", sa.Numeric(6, 2), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sex IN ('male', 'female')"),
        sa.CheckConstraint("bodyweight > 0"),
    )
    op.create_table(
        "lift_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("movement", sa.String(16), nullable=False),
        sa.Column("lifted", sa.Numeric(6, 2), nullable=False),
        sa.Column("bodyweight", sa.Numeric(6, 2), nullable=False),
        sa.Column("sex", sa.String(10), nullable=False),
        sa.Column("formula_version", sa.String(32), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("submission_key", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "submission_key"),
        sa.CheckConstraint("movement IN ('bench', 'squat', 'deadlift')"),
        sa.CheckConstraint("lifted > 0 AND bodyweight > 0"),
        sa.CheckConstraint("sex IN ('male', 'female')"),
    )
    op.create_index("ix_lift_results_user_id", "lift_results", ["user_id"])


def downgrade():
    op.drop_table("lift_results")
    op.drop_table("users")
