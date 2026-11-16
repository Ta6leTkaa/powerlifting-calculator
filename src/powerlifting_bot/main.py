import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from powerlifting_bot.config import Settings
from powerlifting_bot.services import Service
from powerlifting_bot.telegram.handlers import router


async def main():
    settings = Settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    service = Service(async_sessionmaker(engine, expire_on_commit=False))
    dispatcher = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    dispatcher.include_router(router)
    try:
        async with Bot(settings.bot_token.get_secret_value()) as bot:
            await dispatcher.start_polling(bot, service=service, settings=settings)
    finally:
        await dispatcher.storage.close()
        await engine.dispose()


def run():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())


if __name__ == "__main__":
    run()
