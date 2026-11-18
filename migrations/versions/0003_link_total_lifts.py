"""Link three individual results to every total, including existing totals."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("lift_results") as batch:
        batch.add_column(sa.Column("total_result_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_lift_total_result", "total_results", ["total_result_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_unique_constraint("uq_lift_total_movement", ["total_result_id", "movement"])
    total = sa.table(
        "total_results",
        *[
            sa.column(name)
            for name in (
                "id",
                "user_id",
                "squat",
                "bench",
                "deadlift",
                "bodyweight",
                "sex",
                "formula_version",
                "performed_on",
                "created_at",
                "updated_at",
            )
        ],
    )
    columns = [
        "user_id",
        "total_result_id",
        "movement",
        "lifted",
        "bodyweight",
        "sex",
        "formula_version",
        "performed_on",
        "submission_key",
        "created_at",
        "updated_at",
    ]
    lift = sa.table("lift_results", *[sa.column(name) for name in columns])
    for movement in ("squat", "bench", "deadlift"):
        op.execute(
            lift.insert().from_select(
                columns,
                sa.select(
                    total.c.user_id,
                    total.c.id,
                    sa.literal(movement),
                    total.c[movement],
                    total.c.bodyweight,
                    total.c.sex,
                    total.c.formula_version,
                    total.c.performed_on,
                    sa.literal("total:")
                    + sa.cast(total.c.id, sa.String())
                    + sa.literal(f":{movement}"),
                    total.c.created_at,
                    total.c.updated_at,
                ),
            )
        )


def downgrade():
    lift = sa.table("lift_results", sa.column("total_result_id"))
    op.execute(lift.delete().where(lift.c.total_result_id.is_not(None)))
    with op.batch_alter_table("lift_results") as batch:
        batch.drop_constraint("uq_lift_total_movement", type_="unique")
        batch.drop_constraint("fk_lift_total_result", type_="foreignkey")
        batch.drop_column("total_result_id")
