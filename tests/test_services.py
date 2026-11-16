from datetime import date, timedelta
from decimal import Decimal as D

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from powerlifting_bot.db.models import Base, User
from powerlifting_bot.services import Service


@pytest_asyncio.fixture
async def service():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield Service(sessions)
    await engine.dispose()


async def test_registration_history_snapshot_and_duplicate(service):
    user = await service.register(123, "Атлет", "male", D(85), "Europe/Moscow")
    await service.register(123, "Другой ник", "male", D(90), "Europe/Moscow")
    assert (await service.user(123)).nickname == "Атлет"
    first = await service.add_bench(123, D(130), D(85), date(2020, 1, 2), "one")
    duplicate = await service.add_bench(123, D(130), D(85), date(2020, 1, 2), "one")
    assert duplicate.id == first.id
    async with service.sessions() as session:
        stored = await session.get(User, user.id)
        stored.bodyweight = D(90)
        stored.sex = "female"
        await session.commit()
    history = await service.history(123)
    assert len(history) == 1
    assert history[0].bodyweight == D(85)
    assert history[0].sex == "male"
    assert history[0].performed_on == date(2020, 1, 2)
    assert history[0].created_at.date() != date(2020, 1, 2)
    assert await service.history(999) == []


async def test_missing_profile_and_future_date(service):
    with pytest.raises(ValueError):
        await service.add_bench(123, D(130), D(85), date(2020, 1, 1), "x")
    await service.register(123, "Атлет", "male", D(85), "UTC")
    with pytest.raises(ValueError):
        await service.add_bench(123, D(130), D(85), date.today() + timedelta(days=2), "x")


async def test_history_order_and_pagination(service):
    await service.register(123, "Атлет", "male", D(85), "UTC")
    for day in range(1, 8):
        await service.add_bench(123, D(100), D(85), date(2020, 1, day), str(day))
    assert len(await service.history(123)) == 6  # five visible + next-page sentinel
    second = await service.history(123, 1)
    assert [row.performed_on.day for row in second] == [2, 1]


async def test_edit_preserves_snapshot_and_creation_time(service):
    user = await service.register(123, "Атлет", "male", D(85), "UTC")
    original = await service.add_bench(123, D(130), D(85), date(2020, 1, 2), "edit")
    async with service.sessions() as session:
        stored = await session.get(User, user.id)
        stored.sex = "female"
        stored.bodyweight = D(70)
        await session.commit()
    updated = await service.update_result(123, original.id, D(140), D(160), date(2020, 2, 1))
    persisted = await service.result(123, original.id)
    assert persisted.lifted == D(140)
    assert persisted.bodyweight == D(160)  # Valid under original male formula only.
    assert persisted.sex == "male"
    assert persisted.formula_version == original.formula_version
    assert persisted.created_at == original.created_at.replace(tzinfo=None)
    assert persisted.updated_at > persisted.created_at
    assert updated.performed_on == date(2020, 2, 1)
    assert len(await service.history(123)) == 1
    assert (await service.user(123)).bodyweight == D(70)


async def test_edit_rejects_other_users_missing_and_invalid_values(service):
    await service.register(123, "Атлет", "male", D(85), "UTC")
    await service.register(456, "Другой", "male", D(90), "UTC")
    original = await service.add_bench(123, D(130), D(85), date(2020, 1, 2), "edit")
    assert await service.result(456, original.id) is None
    for owner, result_id, lifted, bodyweight, day in [
        (456, original.id, D(140), D(85), date(2020, 1, 1)),
        (123, 99999, D(140), D(85), date(2020, 1, 1)),
        (123, original.id, D(0), D(85), date(2020, 1, 1)),
        (123, original.id, D("140.001"), D(85), date(2020, 1, 1)),
        (123, original.id, D(140), D(20), date(2020, 1, 1)),
        (123, original.id, D(140), D(85), date.today() + timedelta(days=2)),
    ]:
        with pytest.raises(ValueError):
            await service.update_result(owner, result_id, lifted, bodyweight, day)
    assert (await service.result(123, original.id)).lifted == D(130)


async def test_delete_requires_owner(service):
    await service.register(123, "Атлет", "male", D(85), "UTC")
    await service.register(456, "Другой", "male", D(90), "UTC")
    row = await service.add_bench(123, D(130), D(85), date(2020, 1, 2), "delete")
    with pytest.raises(ValueError):
        await service.delete_result(456, row.id)
    assert await service.result(123, row.id) is not None
    await service.delete_result(123, row.id)
    assert await service.history(123) == []
    with pytest.raises(ValueError):
        await service.delete_result(123, row.id)
