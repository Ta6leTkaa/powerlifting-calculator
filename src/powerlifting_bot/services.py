from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from powerlifting_bot.db.models import LiftResult, User
from powerlifting_bot.domain.wilks import FORMULA_VERSION, parse_weight, wilks


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

    async def add_bench(
        self,
        telegram_id: int,
        lifted: Decimal,
        bodyweight: Decimal,
        performed_on: date,
        submission_key: str,
    ):
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
                movement="bench",
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

    async def result(self, telegram_id: int, result_id: int):
        async with self.sessions() as session:
            return await session.scalar(
                select(LiftResult)
                .join(User)
                .where(User.telegram_id == telegram_id, LiftResult.id == result_id)
            )

    async def update_result(
        self,
        telegram_id: int,
        result_id: int,
        lifted: Decimal,
        bodyweight: Decimal,
        performed_on: date,
    ):
        async with self.sessions() as session:
            row = await session.scalar(
                select(LiftResult)
                .join(User)
                .where(User.telegram_id == telegram_id, LiftResult.id == result_id)
            )
            if row is None:
                raise ValueError("Запись не найдена.")
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

    async def delete_result(self, telegram_id: int, result_id: int):
        async with self.sessions() as session:
            row = await session.scalar(
                select(LiftResult)
                .join(User)
                .where(User.telegram_id == telegram_id, LiftResult.id == result_id)
            )
            if row is None:
                raise ValueError("Запись не найдена.")
            await session.delete(row)
            await session.commit()

    async def history(self, telegram_id: int, page: int = 0):
        async with self.sessions() as session:
            query = (
                select(LiftResult)
                .join(User)
                .where(User.telegram_id == telegram_id)
                .order_by(LiftResult.performed_on.desc(), LiftResult.id.desc())
                .offset(max(page, 0) * 5)
                .limit(6)
            )
            return list((await session.scalars(query)).all())
