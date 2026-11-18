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


@pytest.mark.parametrize("movement", ["bench", "squat", "deadlift"])
async def test_individual_categories_are_separate(service, movement):
    await service.register(123, "Атлет", "male", D(85), "UTC")
    row = await service.add_lift(123, D("150.5"), D(85), date(2020, 1, 2), movement, movement)
    assert (await service.result(123, row.id, movement)).movement == movement
    assert len(await service.history(123, category=movement)) == 1
    assert await service.history(123, category="total") == []
    other = "squat" if movement != "squat" else "bench"
    assert await service.result(123, row.id, other) is None
    with pytest.raises(ValueError):
        await service.update_result(123, row.id, D(200), D(85), date(2020, 1, 2), category=other)
    await service.update_result(123, row.id, D(160), D(85), date(2020, 1, 3), category=movement)
    assert (await service.result(123, row.id, movement)).lifted == D(160)


async def test_total_is_atomic_separate_and_idempotent(service):
    await service.register(123, "Атлет", "male", D(85), "UTC")
    day = date(2020, 1, 2)
    single = await service.add_bench(123, D(130), D(85), day, "single")
    row = await service.add_total(123, D(400), D(300), D(400), D(85), day, "total")
    duplicate = await service.add_total(123, D(400), D(300), D(400), D(85), day, "total")
    assert duplicate.id == row.id
    assert row.lifted == D(1100)
    assert row.performed_on == day
    assert len(await service.history(123, category="total")) == 1
    assert len(await service.history(123)) == 4  # Original bench + three linked lifts.
    assert (await service.result(123, single.id)).lifted == D(130)
    updated = await service.update_total(
        123, row.id, D(410), D(300), D(400), D(84), date(2020, 2, 1)
    )
    assert updated.lifted == D(1110)
    assert updated.created_at.replace(tzinfo=None) == row.created_at.replace(tzinfo=None)
    assert (await service.user(123)).bodyweight == D(85)
    for movement, expected in [("squat", D(410)), ("bench", D(300)), ("deadlift", D(400))]:
        rows = await service.history(123, category=movement)
        child = next(item for item in rows if item.total_result_id == row.id)
        assert child.lifted == expected
        assert child.bodyweight == D(84)
        assert child.performed_on == date(2020, 2, 1)
        with pytest.raises(ValueError, match="троеборье"):
            await service.update_result(123, child.id, D(150), D(84), date(2020, 1, 1), movement)
        with pytest.raises(ValueError, match="троеборье"):
            await service.delete_result(123, child.id, movement)
    await service.delete_result(123, row.id, "total")
    assert await service.history(123, category="total") == []
    assert len(await service.history(123)) == 1
    assert await service.result(123, single.id) is not None  # IDs may overlap across tables.


@pytest.mark.parametrize("bad", [None, D(0), D(-1), D("NaN"), D("1000.01")])
async def test_total_requires_three_valid_weights(service, bad):
    await service.register(123, "Атлет", "male", D(85), "UTC")
    with pytest.raises(ValueError):
        await service.add_total(123, D(200), D(130), bad, D(85), date(2020, 1, 2), "bad")
    assert await service.history(123, category="total") == []


async def test_total_permissions_snapshot_and_invalid_update(service):
    user = await service.register(123, "Атлет", "male", D(85), "UTC")
    await service.register(456, "Другой", "male", D(90), "UTC")
    row = await service.add_total(123, D(200), D(130), D(220), D(85), date(2020, 1, 2), "total")
    assert await service.result(456, row.id, "total") is None
    with pytest.raises(ValueError):
        await service.update_total(456, row.id, D(210), D(130), D(220), D(85), date(2020, 1, 2))
    with pytest.raises(ValueError):
        await service.delete_result(456, row.id, "total")
    with pytest.raises(ValueError):
        await service.update_total(123, row.id, D(210), D(130), D(0), D(85), date(2020, 1, 2))
    assert (await service.result(123, row.id, "total")).squat == D(200)
    async with service.sessions() as session:
        stored = await session.get(User, user.id)
        stored.sex = "female"
        await session.commit()
    updated = await service.update_total(
        123, row.id, D(210), D(130), D(220), D(160), date(2020, 2, 1)
    )
    assert updated.sex == "male"
    with pytest.raises(ValueError):
        await service.add_total(
            123, D(200), D(130), D(220), D(85), date.today() + timedelta(days=2), "future"
        )


async def test_best_results_include_linked_lifts_and_recalculate(service):
    await service.register(123, "Атлет", "male", D(85), "UTC")
    await service.register(456, "Другой", "male", D(90), "UTC")
    assert all(row is None for row in (await service.best_results(123)).values())
    day = date(2020, 1, 2)
    bench = await service.add_bench(123, D(150), D(85), day, "bench")
    total = await service.add_total(123, D(200), D(130), D(220), D(84), day, "total")
    await service.add_bench(456, D(500), D(90), day, "other")
    # The best single lifts can belong to different dates, but the best total cannot.
    await service.add_lift(123, D(300), D(85), day, "squat", "squat")
    await service.add_lift(123, D(320), D(85), day, "deadlift", "deadlift")
    best = await service.best_results(123)
    assert best["bench"].id == bench.id
    assert best["squat"].lifted == D(300)
    assert best["deadlift"].lifted == D(320)
    assert best["total"].lifted == D(550)  # Not the sum of unrelated single-lift records.
    await service.update_total(123, total.id, D(210), D(160), D(230), D(83), date(2020, 1, 3))
    best = await service.best_results(123)
    assert best["bench"].lifted == D(160)
    assert best["total"].lifted == D(600)
    await service.delete_result(123, total.id, "total")
    best = await service.best_results(123)
    assert best["bench"].lifted == D(150)
    assert best["total"] is None
    await service.update_result(123, bench.id, D(100), D(85), day)
    assert (await service.best_results(123))["bench"].lifted == D(100)


async def test_best_results_choose_weight_before_date_and_use_full_history(service):
    await service.register(123, "Атлет", "male", D(85), "UTC")
    record = await service.add_bench(123, D(150), D(85), date(2019, 1, 1), "record")
    for day in range(1, 8):
        await service.add_bench(123, D(100), D(85), date(2020, 1, day), f"day-{day}")
    assert (await service.best_results(123))["bench"].id == record.id
    newer = await service.add_bench(123, D(150), D(85), date(2020, 2, 1), "same-weight")
    assert (await service.best_results(123))["bench"].id == newer.id
