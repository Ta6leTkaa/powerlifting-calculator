"""Separate complete three-lift performances from individual lifts."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "total_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("squat", sa.Numeric(6, 2), nullable=False),
        sa.Column("bench", sa.Numeric(6, 2), nullable=False),
        sa.Column("deadlift", sa.Numeric(6, 2), nullable=False),
        sa.Column("bodyweight", sa.Numeric(6, 2), nullable=False),
        sa.Column("sex", sa.String(10), nullable=False),
        sa.Column("formula_version", sa.String(32), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("submission_key", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "submission_key"),
        sa.CheckConstraint("squat > 0 AND bench > 0 AND deadlift > 0 AND bodyweight > 0"),
        sa.CheckConstraint("sex IN ('male', 'female')"),
    )
    op.create_index("ix_total_results_user_id", "total_results", ["user_id"])


def downgrade():
    op.drop_table("total_results")
