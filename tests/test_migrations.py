"""Exercise upgrades and backfill against a database with existing records."""

import os
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from powerlifting_bot.db.models import TotalResult
from powerlifting_bot.services import Service


async def test_upgrade_keeps_existing_results_and_backfills_total_lifts(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'migration.sqlite'}"
    environment = {**os.environ, "DATABASE_URL": database_url, "BOT_TOKEN": "123456:testing"}

    def migrate(*arguments):
        subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    migrate("upgrade", "0002")
    engine = create_async_engine(database_url)
    service = Service(async_sessionmaker(engine, expire_on_commit=False))
    try:
        user = await service.register(123, "Атлет", "male", Decimal(85), "UTC")
        # Seed the old schema without relying on new ORM columns or service behavior.
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO lift_results (user_id, movement, lifted, bodyweight, sex,
                    formula_version, performed_on, submission_key, created_at, updated_at)
                VALUES (:user_id, 'bench', 130, 85, 'male', 'wilks_original',
                    '2020-01-02', 'old', :now, :now)
            """),
                {"user_id": user.id, "now": datetime.now(UTC).isoformat()},
            )
        async with service.sessions() as session:
            total = TotalResult(
                user_id=user.id,
                squat=Decimal(200),
                bench=Decimal(130),
                deadlift=Decimal(220),
                bodyweight=Decimal(85),
                sex="male",
                formula_version="wilks_original",
                performed_on=date(2020, 1, 2),
                submission_key="old-total",
            )
            session.add(total)
            await session.commit()
            total_id = total.id
        migrate("upgrade", "head")
        migrate("check")
        bench_rows = await service.history(123, category="bench")
        assert len(bench_rows) == 2
        assert len(await service.history(123, category="squat")) == 1
        assert len(await service.history(123, category="deadlift")) == 1
        linked = next(row for row in bench_rows if row.total_result_id is not None)
        assert linked.total_result_id == total_id
        assert linked.performed_on == date(2020, 1, 2)
        migrate("upgrade", "head")
        assert len(await service.history(123)) == 4
        # Downgrade removes only generated lifts, preserving the old independent bench.
        migrate("downgrade", "0002")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM lift_results")) == 1
        migrate("upgrade", "head")
        migrate("check")
        assert len(await service.history(123)) == 4
    finally:
        await engine.dispose()
