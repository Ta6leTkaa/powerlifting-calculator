from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from powerlifting_bot.db.models import LiftResult, TotalResult, User
from powerlifting_bot.domain.movements import CATEGORIES, MOVEMENTS
from powerlifting_bot.domain.wilks import FORMULA_VERSION, parse_weight, wilks, wilks_total


class Service:
    def __init__(self, sessions: async_sessionmaker):
        self.sessions = sessions

    async def user(self, telegram_id: int):
        async with self.sessions() as session:
            return await session.scalar(select(User).where(User.telegram_id == telegram_id))

    async def register(self, telegram_id, nickname, sex, bodyweight, timezone):
        if not 1 <= len(nickname.strip()) <= 64:
            raise ValueError("Ник должен содержать от 1 до 64 символов.")
        wilks(sex, bodyweight, Decimal(1))
        ZoneInfo(timezone)
        async with self.sessions() as session:
            user = User(
                telegram_id=telegram_id,
                nickname=nickname.strip(),
                sex=sex,
                bodyweight=bodyweight,
                timezone=timezone,
            )
            session.add(user)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await self.user(telegram_id)
            return user

    async def add_bench(self, telegram_id, lifted, bodyweight, performed_on, submission_key):
        return await self.add_lift(
            telegram_id, lifted, bodyweight, performed_on, submission_key, movement="bench"
        )

    async def add_lift(
        self,
        telegram_id: int,
        lifted: Decimal,
        bodyweight: Decimal,
        performed_on: date,
        submission_key: str,
        movement: str = "bench",
    ):
        if movement not in MOVEMENTS:
            raise ValueError("Неизвестное движение.")
        lifted = parse_weight(str(lifted))
        bodyweight = parse_weight(str(bodyweight))
        async with self.sessions() as session:
            user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                raise ValueError("Сначала создайте профиль через /start.")
            if performed_on > datetime.now(ZoneInfo(user.timezone)).date():
                raise ValueError("Дата результата не может быть в будущем.")
            wilks(user.sex, bodyweight, lifted)
            user_id = user.id
            result = LiftResult(
                user_id=user_id,
                movement=movement,
                lifted=lifted,
                bodyweight=bodyweight,
                sex=user.sex,
                formula_version=FORMULA_VERSION,
                performed_on=performed_on,
                submission_key=submission_key,
            )
            session.add(result)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(LiftResult).where(
                        LiftResult.user_id == user_id, LiftResult.submission_key == submission_key
                    )
                )
                if existing is None:
                    raise
                return existing
            return result

    @staticmethod
    def result_query(telegram_id, category=None):
        if category is not None and category not in CATEGORIES:
            raise ValueError("Неизвестная категория.")
        model = TotalResult if category == "total" else LiftResult
        query = select(model).join(User).where(User.telegram_id == telegram_id)
        if category in MOVEMENTS:
            query = query.where(LiftResult.movement == category)
        return model, query

    async def result(self, telegram_id: int, result_id: int, category=None):
        model, query = self.result_query(telegram_id, category)
        async with self.sessions() as session:
            return await session.scalar(query.where(model.id == result_id))

    async def update_result(
        self,
        telegram_id: int,
        result_id: int,
        lifted: Decimal,
        bodyweight: Decimal,
        performed_on: date,
        category=None,
    ):
        if category == "total":
            raise ValueError("Для троеборья укажите все три движения.")
        async with self.sessions() as session:
            model, query = self.result_query(telegram_id, category)
            row = await session.scalar(query.where(model.id == result_id))
            if row is None:
                raise ValueError("Запись не найдена.")
            if row.total_result_id is not None:
                raise ValueError("Измените эту запись через связанное троеборье.")
            user = await session.get(User, row.user_id)
            if performed_on > datetime.now(ZoneInfo(user.timezone)).date():
                raise ValueError("Дата результата не может быть в будущем.")
            # Validate exact stored precision and use the original record's sex.
            lifted = parse_weight(str(lifted))
            bodyweight = parse_weight(str(bodyweight))
            wilks(row.sex, bodyweight, lifted)
            row.lifted = lifted
            row.bodyweight = bodyweight
            row.performed_on = performed_on
            row.updated_at = datetime.now(ZoneInfo("UTC"))
            await session.commit()
            return row

    async def delete_result(self, telegram_id: int, result_id: int, category=None):
        async with self.sessions() as session:
            model, query = self.result_query(telegram_id, category)
            row = await session.scalar(query.where(model.id == result_id))
            if row is None:
                raise ValueError("Запись не найдена.")
            if isinstance(row, LiftResult) and row.total_result_id is not None:
                raise ValueError("Удалите эту запись через связанное троеборье.")
            if isinstance(row, TotalResult):
                await session.execute(
                    delete(LiftResult).where(LiftResult.total_result_id == row.id)
                )
            await session.delete(row)
            await session.commit()

    async def history(self, telegram_id: int, page: int = 0, category=None):
        model, query = self.result_query(telegram_id, category)
        async with self.sessions() as session:
            query = (
                query.order_by(model.performed_on.desc(), model.id.desc())
                .offset(max(page, 0) * 5)
                .limit(6)
            )
            return list((await session.scalars(query)).all())

    async def best_results(self, telegram_id: int):
        """Best kilograms per discipline; a total must come from one complete performance."""
        best = {}
        async with self.sessions() as session:
            for category in CATEGORIES:
                model, query = self.result_query(telegram_id, category)
                weight = (
                    TotalResult.squat + TotalResult.bench + TotalResult.deadlift
                    if category == "total"
                    else LiftResult.lifted
                )
                best[category] = await session.scalar(
                    query.order_by(weight.desc(), model.performed_on.desc(), model.id.desc()).limit(
                        1
                    )
                )
        return best

    @staticmethod
    async def sync_total_lifts(session, total):
        children = {
            row.movement: row
            for row in (
                await session.scalars(
                    select(LiftResult).where(LiftResult.total_result_id == total.id)
                )
            ).all()
        }
        for movement in MOVEMENTS:
            row = children.get(movement)
            if row is None:
                row = LiftResult(
                    user_id=total.user_id,
                    total_result_id=total.id,
                    movement=movement,
                    submission_key=f"total:{total.id}:{movement}",
                    created_at=total.created_at,
                )
                session.add(row)
            row.lifted = getattr(total, movement)
            row.bodyweight = total.bodyweight
            row.sex = total.sex
            row.formula_version = total.formula_version
            row.performed_on = total.performed_on
            row.updated_at = total.updated_at

    async def add_total(
        self, telegram_id, squat, bench, deadlift, bodyweight, performed_on, submission_key
    ):
        values = {
            name: parse_weight(str(value))
            for name, value in {"squat": squat, "bench": bench, "deadlift": deadlift}.items()
        }
        bodyweight = parse_weight(str(bodyweight))
        async with self.sessions() as session:
            user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                raise ValueError("Сначала создайте профиль через /start.")
            if performed_on > datetime.now(ZoneInfo(user.timezone)).date():
                raise ValueError("Дата результата не может быть в будущем.")
            wilks_total(user.sex, bodyweight, **values)
            user_id = user.id
            row = TotalResult(
                user_id=user_id,
                bodyweight=bodyweight,
                sex=user.sex,
                formula_version=FORMULA_VERSION,
                performed_on=performed_on,
                submission_key=submission_key,
                **values,
            )
            session.add(row)
            try:
                await session.flush()
                await self.sync_total_lifts(session, row)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(TotalResult).where(
                        TotalResult.user_id == user_id, TotalResult.submission_key == submission_key
                    )
                )
                if existing is None:
                    raise
                return existing
            return row

    async def update_total(
        self, telegram_id, result_id, squat, bench, deadlift, bodyweight, performed_on
    ):
        values = {
            name: parse_weight(str(value))
            for name, value in {"squat": squat, "bench": bench, "deadlift": deadlift}.items()
        }
        bodyweight = parse_weight(str(bodyweight))
        async with self.sessions() as session:
            model, query = self.result_query(telegram_id, "total")
            row = await session.scalar(query.where(model.id == result_id).with_for_update())
            if row is None:
                raise ValueError("Запись не найдена.")
            user = await session.get(User, row.user_id)
            if performed_on > datetime.now(ZoneInfo(user.timezone)).date():
                raise ValueError("Дата результата не может быть в будущем.")
            wilks_total(row.sex, bodyweight, **values)
            for name, value in values.items():
                setattr(row, name, value)
            row.bodyweight = bodyweight
            row.performed_on = performed_on
            row.updated_at = datetime.now(ZoneInfo("UTC"))
            await self.sync_total_lifts(session, row)
            await session.commit()
            return row
