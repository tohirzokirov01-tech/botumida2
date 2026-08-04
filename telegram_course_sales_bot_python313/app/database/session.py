"""
Database Session Management with Async SQLAlchemy 2.0
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config.settings import settings
from app.database.models import Base

is_sqlite = "sqlite" in settings.DATABASE_URL
engine_kwargs = {"echo": False, "future": True}
if not is_sqlite:
    engine_kwargs.update({"pool_size": 20, "max_overflow": 10})

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed initial categories & courses if empty
    async with AsyncSessionLocal() as session:
        try:
            from app.database.models import Category, Course
            from sqlalchemy import select
            res = await session.execute(select(Category))
            if not res.scalars().first():
                cat1 = Category(name="💻 Программирование & IT", slug="it")
                cat2 = Category(name="🎨 Дизайн & UX/UI", slug="design")
                cat3 = Category(name="📈 Маркетинг & Бизнес", slug="marketing")
                session.add_all([cat1, cat2, cat3])
                await session.flush()

                c1 = Course(
                    category_id=cat1.id,
                    title="Python & Telegram-боты с нуля",
                    description="Полный практический курс по разработке Telegram-ботов на aiogram 3, FastAPI и SQLAlchemy.",
                    price_uzs=350000,
                    author="Алексей Громов",
                    telegram_channel_title="Закрытый канал: Python Pro 2026",
                    is_published=True
                )
                c2 = Course(
                    category_id=cat2.id,
                    title="Figma & UX/UI Дизайн 2026",
                    description="Освойте профессию веб-дизайнера: проектирование интерфейсов, мобильные приложения, дизайн-системы.",
                    price_uzs=450000,
                    author="Мария Соколова",
                    telegram_channel_title="Закрытый клуб Figma Masters",
                    is_published=True
                )
                session.add_all([c1, c2])
                await session.commit()
        except Exception:
            await session.rollback()


async def close_db():
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
