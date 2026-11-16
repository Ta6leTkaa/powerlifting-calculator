import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from powerlifting_bot.config import Settings
from powerlifting_bot.db.models import Base


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def main():
    engine = create_async_engine(Settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


asyncio.run(main())
