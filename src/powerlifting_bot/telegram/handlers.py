from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from powerlifting_bot.config import Settings
from powerlifting_bot.domain.movements import CATEGORIES, MOVEMENTS
from powerlifting_bot.domain.wilks import parse_weight, wilks, wilks_total
from powerlifting_bot.services import Service

router = Router()
# This bot handles personal data only in private chats.
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")
MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Записать результат"), KeyboardButton(text="История")],
        [KeyboardButton(text="Профиль")],
    ],
    resize_keyboard=True,
)


def buttons(*rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
            for row in rows
        ]
    )


class Registration(StatesGroup):
    nickname = State()
    sex = State()
    bodyweight = State()


class HistoryState(StatesGroup):
    confirm_delete = State()


class Bench(StatesGroup):
    lifted = State()
    confirm = State()
    bodyweight = State()
    date = State()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ввод отменён. /start — главное меню.")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, service: Service):
    await state.clear()
    if await service.user(message.from_user.id):
        await message.answer("Выберите действие.", reply_markup=MENU)
        return
    await state.set_state(Registration.nickname)
    await message.answer("Создадим профиль. Введите ник пользователя?")


@router.message(Registration.nickname)
async def nickname(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not 1 <= len(value) <= 64 or value.startswith("/"):
        await message.answer("Длина ника: от 1 до 64 символов.")
        return
    await state.update_data(nickname=value)
    await state.set_state(Registration.sex)
    await message.answer(
        "Выберите пол.",
        reply_markup=buttons([("Мужской", "sex:male"), ("Женский", "sex:female")]),
    )


@router.callback_query(Registration.sex, F.data.startswith("sex:"))
async def sex(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    value = callback.data.split(":")[1]
    if value not in {"male", "female"}:
        return
    await state.update_data(sex=value)
    await state.set_state(Registration.bodyweight)
    await callback.message.answer("Введите массу тела в кг. Например: 85,5.\n")


@router.message(Registration.bodyweight)
async def registration_weight(
    message: Message, state: FSMContext, service: Service, settings: Settings
):
    data = await state.get_data()
    try:
        weight = parse_weight(message.text or "")
        user = await service.register(
            message.from_user.id, data["nickname"], data["sex"], weight, settings.default_timezone
        )
    except ValueError as error:
        await message.answer(str(error))
        return
    await state.clear()
    await message.answer(f"Профиль {user.nickname} создан!", reply_markup=MENU)


@router.message(Command("profile"))
@router.message(F.text == "Профиль")
async def profile(message: Message, service: Service):
    user = await service.user(message.from_user.id)
    if not user:
        await message.answer("Сначала создайте профиль: /start")
        return
    sex_label = "мужской" if user.sex == "male" else "женский"
    best = await service.best_results(message.from_user.id)
    records = []
    for category in ("bench", "squat", "deadlift", "total"):
        row = best[category]
        value = (
            f"{kg(row.lifted)} кг ({score_for(row_data(row)):.2f} Wilks) · {row.performed_on:%d.%m.%Y}"
            if row
            else "нет записей"
        )
        records.append(f"{CATEGORIES[category]}: {value}")
    await message.answer(
        f"Ник: {user.nickname}\nПол для расчёта: {sex_label}\n"
        f"Масса тела: {user.bodyweight:g} кг\nЧасовой пояс: {user.timezone}"
        + "\n\nЛучшие результаты по весу\n"
        + "\n".join(records),
        reply_markup=MENU,
    )


def category_keyboard(prefix):
    return buttons(
        [("Жим", f"{prefix}bench"), ("Присед", f"{prefix}squat")],
        [("Тяга", f"{prefix}deadlift"), ("Троеборье", f"{prefix}total")],
    )


async def start_result(
    message: Message, state: FSMContext, service: Service, movement: str, telegram_id: int
):
    user = await service.user(telegram_id)
    if not user:
        await message.answer("Сначала создайте профиль: /start")
        return
    await state.clear()
    await state.update_data(
        movement=movement,
        input_movement="squat" if movement == "total" else movement,
        lifts={},
        sex=user.sex,
        performed_on=datetime.now(ZoneInfo(user.timezone)).date().isoformat(),
        submission_key=str(uuid4()),
    )
    await state.set_state(Bench.lifted)
    text = (
        (
            "Троеборье: введите все три результата за один день.\n"
            "Дата и масса тела будут общими.\n\nПрисед — сколько кг?"
        )
        if movement == "total"
        else (f"{CATEGORIES[movement]} — введите поднятый вес в кг. Например: 100,5.")
    )
    await message.answer(text)


@router.message(Command("bench", "squat", "deadlift", "total"))
async def bench(message: Message, state: FSMContext, service: Service):
    movement = message.text.split()[0].lstrip("/").split("@")[0]
    if movement not in CATEGORIES:
        movement = "bench"
    await start_result(message, state, service, movement, message.from_user.id)


@router.message(Command("record"))
@router.message(F.text.in_({"Записать результат", "Записать жим"}))
async def choose_entry(message: Message, state: FSMContext):
    await state.clear()
    if message.text == "Записать жим":
        await message.answer(
            "Меню обновлено: теперь можно выбрать движение или троеборье.", reply_markup=MENU
        )
    await message.answer("Что записать?", reply_markup=category_keyboard("entry:"))


@router.callback_query(F.data.startswith("entry:"))
async def entry_category(callback: CallbackQuery, state: FSMContext, service: Service):
    movement = callback.data.split(":")[1]
    if movement not in CATEGORIES:
        await callback.answer("Неизвестная категория.")
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await start_result(callback.message, state, service, movement, callback.from_user.id)


def score_for(data):
    if data.get("movement") == "total":
        return wilks_total(
            data["sex"],
            Decimal(data["bodyweight"]),
            **{key: Decimal(value) for key, value in data["lifts"].items()},
        )
    return wilks(data["sex"], Decimal(data["bodyweight"]), Decimal(data["lifted"]))


def lift_text(data):
    if data.get("movement") == "total":
        return (
            "\n".join(f"{label}: {kg(data['lifts'][key])} кг" for key, label in MOVEMENTS.items())
            + f"\nСумма: {kg(data['lifted'])} кг"
        )
    return f"{CATEGORIES[data.get('movement', 'bench')]}: {kg(data['lifted'])} кг"


def history_key(page, category):
    return f"history:{page}" + (f":{category}" if category != "bench" else "")


def record_key(action, result_id, page, category):
    return f"record:{action}:{result_id}:{page}" + (f":{category}" if category != "bench" else "")


def kg(value):
    return format(Decimal(value).normalize(), "f").replace(".", ",")


async def replace_panel(bot, chat_id, message_id, text, keyboard):
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard
        )
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message.lower():
            raise


async def edit_panel(message: Message, state: FSMContext, text, keyboard):
    data = await state.get_data()
    await replace_panel(
        message.bot, data["panel_chat_id"], data["panel_message_id"], text, keyboard
    )


async def active_bench_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    expected = (
        data.get("panel_message_id") if data.get("result_id") else data.get("preview_message_id")
    )
    if expected != callback.message.message_id:
        await callback.answer("Эта кнопка больше не активна.")
        return False
    return True


async def preview(message: Message, state: FSMContext):
    data = await state.get_data()
    score = score_for(data)
    date = datetime.strptime(data["performed_on"], "%Y-%m-%d").strftime("%d.%m.%Y")
    await state.set_state(Bench.confirm)
    text = (
        f"{lift_text(data)}\nМасса тела: {kg(data['bodyweight'])} кг\n"
        f"Дата: {date}\nWilks · {CATEGORIES[data.get('movement', 'bench')]}: {score:.2f} балла"
    )
    if data.get("result_id"):
        await edit_panel(
            message,
            state,
            "Редактирование · изменения ещё не сохранены\n\n" + text,
            buttons(
                [("Сохранить изменения", "bench:save")],
                [("Изменить", "saved:fields")],
                [("Отмена", "bench:cancel")],
            ),
        )
        return
    sent = await message.answer(
        text,
        reply_markup=buttons(
            [("Сохранить", "bench:save")],
            [("Изменить массу", "bench:weight"), ("Изменить дату", "bench:date")],
            [
                (
                    "Изменить движения" if data.get("movement") == "total" else "Изменить вес",
                    "draft:fields" if data.get("movement") == "total" else "bench:lift",
                ),
                ("Отмена", "bench:cancel"),
            ],
        ),
    )
    await state.update_data(preview_message_id=sent.message_id)


@router.message(Bench.lifted, ~F.text.startswith("/"), F.text != "История")
async def lifted(message: Message, state: FSMContext):
    try:
        value = parse_weight(message.text or "")
    except ValueError as error:
        await message.answer(str(error))
        return
    data = await state.get_data()
    if data.get("movement") == "total":
        lifts = dict(data["lifts"])
        lifts[data["input_movement"]] = str(value)
        await state.update_data(lifts=lifts)
        missing = [key for key in MOVEMENTS if key not in lifts]
        if missing:
            await state.update_data(input_movement=missing[0])
            await message.answer(f"{MOVEMENTS[missing[0]]} — сколько кг?")
            return
        value = sum(Decimal(weight) for weight in lifts.values())
    await state.update_data(lifted=str(value))
    if "bodyweight" not in data:
        await state.set_state(Bench.bodyweight)
        await message.answer("Введите вашу массу тела на дату результата в кг. Например: 85,5.")
        return
    await preview(message, state)


@router.callback_query(Bench.confirm, F.data == "bench:weight")
async def edit_weight(callback: CallbackQuery, state: FSMContext):
    if not await active_bench_callback(callback, state):
        return
    await callback.answer()
    data = await state.get_data()
    if data.get("result_id"):
        await state.set_state(Bench.bodyweight)
        await edit_panel(
            callback.message,
            state,
            "Введите массу тела на дату результата. Профиль останется прежним.",
            buttons([("← Назад", "saved:fields")]),
        )
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(Bench.bodyweight)
    await callback.message.answer(
        "Введите массу тела на дату результата. Профиль останется прежним."
    )


@router.message(Bench.bodyweight, ~F.text.startswith("/"), F.text != "История")
async def bodyweight(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        value = parse_weight(message.text or "")
        score_for({**data, "bodyweight": str(value)})
    except ValueError as error:
        await message.answer(str(error))
        return
    await state.update_data(bodyweight=str(value))
    await preview(message, state)


@router.callback_query(Bench.confirm, F.data == "bench:date")
async def edit_date(callback: CallbackQuery, state: FSMContext):
    if not await active_bench_callback(callback, state):
        return
    await callback.answer()
    data = await state.get_data()
    if data.get("result_id"):
        await state.set_state(Bench.date)
        await edit_panel(
            callback.message,
            state,
            "Введите дату результата: ДД.ММ.ГГГГ. Например: 15.11.2026.",
            buttons([("← Назад", "saved:fields")]),
        )
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(Bench.date)
    await callback.message.answer("Введите дату результата: ДД.ММ.ГГГГ. Например: 15.11.2026.")


@router.message(Bench.date, ~F.text.startswith("/"), F.text != "История")
async def performed_on(message: Message, state: FSMContext, service: Service):
    user = await service.user(message.from_user.id)
    try:
        value = datetime.strptime(message.text or "", "%d.%m.%Y").date()
        if value > datetime.now(ZoneInfo(user.timezone)).date():
            raise ValueError
    except ValueError:
        await message.answer("Введите существующую дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(performed_on=value.isoformat())
    await preview(message, state)


@router.callback_query(Bench.confirm, F.data == "bench:lift")
async def edit_lift(callback: CallbackQuery, state: FSMContext):
    if not await active_bench_callback(callback, state):
        return
    await callback.answer()
    data = await state.get_data()
    if data.get("result_id"):
        await state.set_state(Bench.lifted)
        await edit_panel(
            callback.message,
            state,
            "Введите вес штанги в кг.",
            buttons([("← Назад", "saved:fields")]),
        )
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(Bench.lifted)
    await callback.message.answer("Введите вес штанги в кг.")


@router.callback_query(Bench.confirm, F.data == "bench:cancel")
async def cancel_bench(callback: CallbackQuery, state: FSMContext, service: Service):
    if not await active_bench_callback(callback, state):
        return
    data = await state.get_data()
    if data.get("result_id"):
        await callback.answer("Изменения отменены")
        await state.clear()
        await show_card(
            callback.message,
            callback.from_user.id,
            service,
            data["result_id"],
            data["history_page"],
            category=data.get("movement", "bench"),
        )
        return
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Запись отменена.", reply_markup=MENU)


@router.callback_query(Bench.confirm, F.data == "bench:save")
async def save(callback: CallbackQuery, state: FSMContext, service: Service):
    if not await active_bench_callback(callback, state):
        return
    await callback.answer()
    data = await state.get_data()
    try:
        values = {
            "telegram_id": callback.from_user.id,
            "bodyweight": Decimal(data["bodyweight"]),
            "performed_on": datetime.strptime(data["performed_on"], "%Y-%m-%d").date(),
        }
        if data.get("movement") == "total":
            values.update({key: Decimal(value) for key, value in data["lifts"].items()})
            if data.get("result_id"):
                await service.update_total(result_id=data["result_id"], **values)
            else:
                await service.add_total(submission_key=data["submission_key"], **values)
        else:
            values["lifted"] = Decimal(data["lifted"])
            if data.get("result_id"):
                await service.update_result(
                    result_id=data["result_id"], category=data.get("movement", "bench"), **values
                )
            else:
                await service.add_lift(
                    submission_key=data["submission_key"],
                    movement=data.get("movement", "bench"),
                    **values,
                )
    except ValueError as error:
        await callback.message.answer(str(error))
        return
    await state.clear()
    if data.get("result_id"):
        await show_card(
            callback.message,
            callback.from_user.id,
            service,
            data["result_id"],
            data["history_page"],
            "Изменения сохранены!\n\n",
            category=data.get("movement", "bench"),
        )
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Результат сохранён!", reply_markup=MENU)


async def show_history(
    message: Message, telegram_id: int, service: Service, page: int, *, edit=False, category="bench"
):
    rows = await service.history(telegram_id, page, category=category)
    # A date change or deletion may have removed the last record on this page.
    if not rows and page > 0:
        page -= 1
        rows = await service.history(telegram_id, page, category=category)
        if not rows:
            page = 0
            rows = await service.history(telegram_id, page, category=category)
    entries = []
    choices = []
    for number, row in enumerate(rows[:5], start=1):
        score = score_for(row_data(row))
        entries.append(
            f"{number}. {row.performed_on:%d.%m.%Y} · {CATEGORIES[row.movement]} {kg(row.lifted)} кг · {score:.2f} Wilks"
        )
        choices.append((str(number), record_key("view", row.id, page, category)))
    navigation = []
    if page > 0:
        navigation.append(("← Назад", history_key(page - 1, category)))
    if len(rows) > 5:
        navigation.append(("Далее →", history_key(page + 1, category)))
    text = (
        (
            f"История · {CATEGORIES[category]} · Страница {page + 1}\n\n"
            + "\n".join(entries)
            + "\n\nВыберите запись для просмотра."
        )
        if rows
        else "Записей пока нет."
    )
    keyboard = buttons(
        *([choices] if choices else []),
        *([navigation] if navigation else []),
        [("← Категории", "history:categories")],
    )
    if edit:
        await replace_panel(message.bot, message.chat.id, message.message_id, text, keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


async def show_card(
    message: Message,
    telegram_id: int,
    service: Service,
    result_id: int,
    page: int,
    notice="",
    *,
    category="bench",
):
    row = await service.result(telegram_id, result_id, category=category)
    if row is None:
        await replace_panel(
            message.bot,
            message.chat.id,
            message.message_id,
            "Запись не найдена.",
            buttons([("← К истории", history_key(page, category))]),
        )
        return
    score = score_for(row_data(row))
    linked_total_id = getattr(row, "total_result_id", None)
    actions = (
        [("Открыть троеборье", record_key("view", linked_total_id, 0, "total"))]
        if linked_total_id is not None
        else [
            ("Изменить", record_key("edit", row.id, page, category)),
            ("Удалить", record_key("delete", row.id, page, category)),
        ]
    )
    source = "\n\nИз записи троеборья. Изменения доступны в её карточке." if linked_total_id else ""
    await replace_panel(
        message.bot,
        message.chat.id,
        message.message_id,
        notice + f"{CATEGORIES[row.movement]} · {row.performed_on:%d.%m.%Y}\n\n"
        f"{lift_text(row_data(row))}\nМасса тела: {kg(row.bodyweight)} кг\n"
        f"Wilks: {score:.2f}" + source,
        buttons(
            actions,
            [("← К истории", history_key(page, category))],
        ),
    )


@router.message(Command("history"))
@router.message(F.text == "История")
async def history(message: Message, state: FSMContext, service: Service):
    await state.clear()
    await message.answer(
        "История — выберите категорию.", reply_markup=category_keyboard("history:0:")
    )


@router.callback_query(F.data.startswith("history:"))
async def history_page(callback: CallbackQuery, state: FSMContext, service: Service):
    await callback.answer()
    await state.clear()
    if callback.data == "history:categories":
        await replace_panel(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            "История — выберите категорию.",
            category_keyboard("history:0:"),
        )
        return
    try:
        parts = callback.data.split(":")
        page = int(parts[1])
        category = parts[2] if len(parts) == 3 else "bench"
        if not 0 <= page <= 100000 or category not in CATEGORIES:
            raise ValueError
    except (ValueError, IndexError):
        return
    await show_history(
        callback.message, callback.from_user.id, service, page, edit=True, category=category
    )


@router.callback_query(F.data.startswith("record:"))
async def record_action(callback: CallbackQuery, state: FSMContext, service: Service):
    try:
        parts = callback.data.split(":")
        _, action, result_id, page = parts[:4]
        category = parts[4] if len(parts) == 5 else "bench"
        if category not in CATEGORIES or len(parts) not in {4, 5}:
            raise ValueError
        result_id, page = int(result_id), int(page)
        if not 0 < result_id < 2**31 or not 0 <= page <= 100000:
            raise ValueError
        if action not in {"view", "edit", "delete", "remove"}:
            raise ValueError
    except ValueError:
        await callback.answer("Эта кнопка больше не активна.")
        return
    row = await service.result(callback.from_user.id, result_id, category=category)
    if row is None:
        await callback.answer("Запись не найдена.")
        await state.clear()
        await show_history(
            callback.message, callback.from_user.id, service, page, edit=True, category=category
        )
        return
    if action != "view" and getattr(row, "total_result_id", None) is not None:
        await callback.answer("Эта запись связана с троеборьем.")
        await state.clear()
        await show_card(
            callback.message,
            callback.from_user.id,
            service,
            row.total_result_id,
            0,
            category="total",
        )
        return
    if action == "remove":
        data = await state.get_data()
        if (
            await state.get_state() != HistoryState.confirm_delete.state
            or data.get("delete_result_id") != result_id
            or data.get("category") != category
            or data.get("panel_message_id") != callback.message.message_id
        ):
            await callback.answer("Подтвердите удаление заново в карточке записи.")
            return
    await callback.answer()
    await state.clear()
    if action == "view":
        await show_card(
            callback.message, callback.from_user.id, service, result_id, page, category=category
        )
    elif action == "edit":
        await state.update_data(
            **row_data(row),
            result_id=row.id,
            history_page=page,
            panel_chat_id=callback.message.chat.id,
            panel_message_id=callback.message.message_id,
        )
        await show_fields(callback.message, state)
    elif action == "delete":
        await state.set_state(HistoryState.confirm_delete)
        await state.update_data(
            delete_result_id=result_id,
            category=category,
            panel_message_id=callback.message.message_id,
        )
        await replace_panel(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            f"Удалить запись?\n\n{CATEGORIES[row.movement]} {kg(row.lifted)} кг · {row.performed_on:%d.%m.%Y}\n"
            + ("Также удалятся три связанные записи движений.\n" if category == "total" else "")
            + "Это действие нельзя отменить.",
            buttons(
                [("Удалить запись", record_key("remove", row.id, page, category))],
                [("Отмена", record_key("view", row.id, page, category))],
            ),
        )
    else:
        await service.delete_result(callback.from_user.id, result_id, category=category)
        await show_history(
            callback.message, callback.from_user.id, service, page, edit=True, category=category
        )


def row_data(row):
    data = {
        "movement": row.movement,
        "lifted": str(row.lifted),
        "bodyweight": str(row.bodyweight),
        "sex": row.sex,
        "performed_on": row.performed_on.isoformat(),
    }
    if row.movement == "total":
        data["lifts"] = {key: str(getattr(row, key)) for key in MOVEMENTS}
    return data


async def show_fields(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(Bench.confirm)
    rows = (
        [[(label, f"component:{key}") for key, label in MOVEMENTS.items()]]
        if data.get("movement") == "total"
        else [[("Вес штанги", "bench:lift")]]
    )
    keyboard = buttons(
        *rows,
        [("Массу тела", "bench:weight"), ("Дату", "bench:date")],
        [("← Назад", "saved:preview")],
    )
    if data.get("result_id"):
        await edit_panel(message, state, "Что изменить?", keyboard)
    else:
        await replace_panel(
            message.bot, message.chat.id, message.message_id, "Что изменить?", keyboard
        )


@router.callback_query(Bench.confirm, F.data.startswith("component:"))
async def edit_component(callback: CallbackQuery, state: FSMContext):
    if not await active_bench_callback(callback, state):
        return
    key = callback.data.split(":")[1]
    data = await state.get_data()
    if key not in MOVEMENTS or data.get("movement") != "total":
        await callback.answer("Эта кнопка больше не активна.")
        return
    await callback.answer()
    await state.update_data(input_movement=key)
    await state.set_state(Bench.lifted)
    prompt = f"{MOVEMENTS[key]} — введите вес в кг."
    if data.get("result_id"):
        await edit_panel(callback.message, state, prompt, buttons([("← Назад", "saved:fields")]))
    else:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(prompt)


@router.callback_query(F.data.in_({"draft:fields", "saved:fields", "saved:preview"}))
async def saved_menu(callback: CallbackQuery, state: FSMContext):
    if not await active_bench_callback(callback, state):
        return
    await callback.answer()
    if callback.data in {"saved:fields", "draft:fields"}:
        await show_fields(callback.message, state)
    else:
        await preview(callback.message, state)


@router.callback_query()
async def stale_button(callback: CallbackQuery):
    await callback.answer("Эта кнопка больше не активна. Продолжите ввод или нажмите /start.")


@router.message()
async def fallback(message: Message):
    await message.answer("Используйте кнопки или /start. Отменить текущий ввод: /cancel.")
