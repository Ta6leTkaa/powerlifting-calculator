from datetime import UTC, datetime
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import Chat, Message, Update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from powerlifting_bot.config import Settings
from powerlifting_bot.db.models import Base
from powerlifting_bot.services import Service
from powerlifting_bot.telegram.handlers import router


async def test_registration_bench_confirmation_and_history():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = Service(async_sessionmaker(engine, expire_on_commit=False))
    bot = Bot("123456:abcdefghijklmnopqrstuvwxyz123456789")
    replies = []
    edits = []
    new_messages = []
    keyboards = []

    async def request(bot, method, timeout=None):
        if isinstance(method, (SendMessage, EditMessageText)):
            replies.append(method.text)
            keyboards.append(method.reply_markup)
        if isinstance(method, SendMessage):
            new_messages.append(method)
        if isinstance(method, EditMessageText):
            edits.append(method)
        return Message(
            message_id=100,
            date=datetime.now(UTC),
            chat=Chat(id=123, type="private"),
            text="response",
        )

    bot.session.make_request = AsyncMock(side_effect=request)
    dispatcher = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    dispatcher.include_router(router)
    settings = Settings(bot_token=bot.token, database_url="sqlite+aiosqlite:///:memory:")
    counter = 0

    async def send(text=None, callback=None):
        nonlocal counter
        counter += 1
        message = {
            "message_id": counter,
            "date": 1700000000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 123, "is_bot": False, "first_name": "Test"},
            "text": text or "",
        }
        payload = {"update_id": counter, "message": message}
        if callback:
            message["message_id"] = 100
            payload = {
                "update_id": counter,
                "callback_query": {
                    "id": str(counter),
                    "from": message["from"],
                    "chat_instance": "1",
                    "data": callback,
                    "message": message,
                },
            }
        await dispatcher.feed_update(
            bot, Update.model_validate(payload), service=service, settings=settings
        )

    try:
        await send("/start")
        await send("Атлет")
        await send(callback="sex:male")
        await send("85")
        assert (await service.user(123)).nickname == "Атлет"
        await send("/profile")
        assert replies[-1].count("нет записей") == 4
        await send("/bench")
        await send("130")
        assert "массу тела" in replies[-1]
        await send(callback="bench:save")
        assert await service.history(123) == []
        await send("NaN")
        await send("86,5")
        assert "86,5" in replies[-1]
        assert "Wilks" in replies[-1]
        await send(callback="bench:date")
        await send("02.01.2020")
        await send(callback="bench:weight")
        await send("84,5")
        await send(callback="bench:save")
        await send(callback="bench:save")  # stale double click
        assert len(await service.history(123)) == 1
        await send("/history")
        await send(callback="history:0:bench")
        assert "02.01.2020" in replies[-1]
        assert "130" in replies[-1]
        row = (await service.history(123))[0]
        message_count = len(new_messages)
        await send(callback=f"record:view:{row.id}:0")
        assert "Масса тела:" in replies[-1]
        await send(callback=f"record:edit:{row.id}:0")
        await send(callback="bench:lift")
        await send("140")
        await send(callback="saved:fields")
        await send(callback="bench:weight")
        await send("83")
        await send(callback="saved:fields")
        await send(callback="bench:date")
        await send("03.01.2020")
        await send(callback="bench:save")
        await send(callback="bench:save")
        history = await service.history(123)
        assert len(history) == 1
        assert str(history[0].lifted) == "140.00"
        assert str(history[0].bodyweight) == "83.00"
        assert len(new_messages) == message_count
        await send("/history")
        await send(callback="history:0:bench")
        assert "03.01.2020" in replies[-1]
        assert "140" in replies[-1]
        assert "130" not in replies[-1]
        await send(callback=f"record:view:{row.id}:0")
        assert "Масса тела:" in replies[-1]
        await send(callback=f"record:edit:{row.id}:0")
        await send(callback="bench:lift")
        await send("150")
        await send(callback="bench:cancel")
        assert (await service.result(123, row.id)).lifted == 140
        # Browsing and deletion confirmations edit the original panel.
        assert all(edit.message_id == 100 for edit in edits)
        await send(callback=f"record:delete:{row.id}:0")
        assert await service.result(123, row.id) is not None
        await send(callback=f"record:view:{row.id}:0")  # cancel deletion
        assert "140" in replies[-1]
        await send(callback=f"record:remove:{row.id}:0")  # stale confirmation after cancel
        assert await service.result(123, row.id) is not None
        # Add enough records to verify compact choices and page preservation.
        from datetime import date
        from decimal import Decimal

        for day in range(1, 8):
            await service.add_bench(123, Decimal(100), Decimal(85), date(2021, 1, day), str(day))
        await send("/history")
        await send(callback="history:0:bench")
        assert len(keyboards[-1].inline_keyboard[0]) == 5
        await send(callback="history:1")
        assert "Страница 2" in replies[-1]
        await send(callback=f"record:view:{row.id}:1")
        assert keyboards[-1].inline_keyboard[-1][0].callback_data == "history:1"
        await send(callback=f"record:edit:{row.id}:1")
        await send(callback="saved:preview")
        await send(callback="bench:cancel")
        await send(callback="history:1")
        assert "Страница 2" in replies[-1]
        await send(callback=f"record:delete:{row.id}:1")
        await send(callback=f"record:remove:{row.id}:1")
        assert await service.result(123, row.id) is None
        assert "Страница 2" in replies[-1]
        # A stale confirmation is harmless.
        await send(callback=f"record:remove:{row.id}:1")
        # Individual categories use their own entry form and filtered history.
        for movement, label, weight in [("squat", "Присед", "180"), ("deadlift", "Тяга", "220")]:
            await send("Записать результат")
            await send(callback=f"entry:{movement}")
            await send(weight)
            assert "массу тела" in replies[-1]
            await send("82")
            assert label in replies[-1]
            await send(callback="bench:save")
            records = await service.history(123, category=movement)
            assert len(records) == 1
            await send("/history")
            await send(callback=f"history:0:{movement}")
            assert label in replies[-1]
            await send(callback=f"record:view:{records[0].id}:0:{movement}")
            assert keyboards[-1].inline_keyboard[-1][0].callback_data == f"history:0:{movement}"

        await send("Записать жим")  # Legacy keyboard now opens the category picker.
        assert replies[-1] == "Что записать?"
        assert {button.text for row in keyboards[-1].inline_keyboard for button in row} == {
            "Жим",
            "Присед",
            "Тяга",
            "Троеборье",
        }
        refreshed = new_messages[-2].reply_markup
        assert refreshed.keyboard[0][0].text == "Записать результат"
        # An incomplete total never appears in history.
        await send("/total")
        await send("400")
        await send(callback="bench:save")
        assert await service.history(123, category="total") == []
        await send("/cancel")
        await send("Записать результат")
        await send(callback="entry:total")
        await send("400")
        assert "Жим" in replies[-1]
        await send("300")
        assert "Тяга" in replies[-1]
        await send("0")
        assert await service.history(123, category="total") == []
        await send("400")
        assert "массу тела" in replies[-1]
        await send("83")
        assert "Сумма: 1100 кг" in replies[-1]
        await send(callback="draft:fields")
        await send(callback="component:squat")
        await send("410")
        assert "Сумма: 1110 кг" in replies[-1]
        await send(callback="bench:date")
        await send("04.01.2020")
        await send(callback="bench:save")
        await send(callback="bench:save")
        totals = await service.history(123, category="total")
        assert len(totals) == 1
        total = totals[0]
        assert total.bodyweight == 83
        await send("Профиль")
        assert "Жим: 300 кг" in replies[-1]
        assert "Присед: 410 кг" in replies[-1]
        assert "Тяга: 400 кг" in replies[-1]
        assert "Троеборье: 1110 кг" in replies[-1]
        child = next(
            item
            for item in await service.history(123, category="squat")
            if item.total_result_id == total.id
        )
        await send(callback=f"record:view:{child.id}:0:squat")
        assert "Из записи троеборья" in replies[-1]
        assert (
            keyboards[-1].inline_keyboard[0][0].callback_data == f"record:view:{total.id}:0:total"
        )
        await send("/history")
        await send(callback="history:0:total")
        assert "Троеборье" in replies[-1]
        await send(callback=f"record:view:{total.id}:0:total")
        assert "Присед: 410 кг" in replies[-1]
        assert "Жим: 300 кг" in replies[-1]
        assert "Тяга: 400 кг" in replies[-1]
        await send(callback=f"record:edit:{total.id}:0:total")
        await send(callback="component:bench")
        await send("310")
        assert "Сумма: 1120 кг" in replies[-1]
        await send(callback="saved:fields")
        await send(callback="bench:weight")
        await send("84")
        await send(callback="saved:fields")
        await send(callback="bench:date")
        await send("05.01.2020")
        await send(callback="bench:save")
        updated = await service.result(123, total.id, "total")
        assert updated.bench == 310
        assert updated.performed_on.isoformat() == "2020-01-05"
        assert updated.squat == 410 and updated.deadlift == 400
        assert keyboards[-1].inline_keyboard[-1][0].callback_data == "history:0:total"
        await send(callback=f"record:edit:{total.id}:0:total")
        await send(callback="component:deadlift")
        await send("450")
        await send(callback="bench:cancel")
        assert (await service.result(123, total.id, "total")).deadlift == 400
        await send(callback=f"record:delete:{total.id}:0:total")
        await send(callback=f"record:remove:{total.id}:0:total")
        assert await service.history(123, category="total") == []
        assert len(await service.history(123, category="squat")) == 1
        assert keyboards[-1].inline_keyboard[-1][0].callback_data == "history:categories"
    finally:
        await dispatcher.storage.close()
        await bot.session.close()
        await engine.dispose()
