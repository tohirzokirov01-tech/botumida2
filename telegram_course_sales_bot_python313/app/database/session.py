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
    engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800
    })

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
        from sqlalchemy import text
        if "sqlite" in settings.DATABASE_URL:
            sqlite_migrations = [
                "ALTER TABLE users ADD COLUMN language VARCHAR(16) DEFAULT 'ru';",
                "ALTER TABLE courses ADD COLUMN has_tiers BOOLEAN DEFAULT 0;",
                "ALTER TABLE orders ADD COLUMN tier_id INTEGER;",
                "ALTER TABLE orders ADD COLUMN tier_title VARCHAR(128);",
                "ALTER TABLE user_course_access ADD COLUMN tier_title VARCHAR(128);",
            ]
            for sql in sqlite_migrations:
                try:
                    await conn.execute(text(sql))
                except Exception:
                    pass
        else:
            pg_migrations = [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(16) DEFAULT 'ru';",
                "ALTER TABLE courses ADD COLUMN IF NOT EXISTS has_tiers BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS tier_id INTEGER;",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS tier_title VARCHAR(128);",
                "ALTER TABLE user_course_access ADD COLUMN IF NOT EXISTS tier_title VARCHAR(128);",
            ]
            for sql in pg_migrations:
                try:
                    await conn.execute(text(sql))
                except Exception:
                    pass

    # Seed initial categories, courses & system settings if empty
    async with AsyncSessionLocal() as session:
        try:
            from app.database.models import Category, Course, SystemSetting
            from sqlalchemy import select

            # Seed system settings if empty
            settings_check = await session.execute(select(SystemSetting).limit(1))
            if not settings_check.scalars().first():
                default_settings = [
                    SystemSetting(key="bot_name", value="Курсы & Обучение Telegram Bot"),
                    SystemSetting(key="support_username", value="@course_support_uz"),
                    SystemSetting(key="admin_group_id", value="-100293847561"),
                    SystemSetting(key="default_currency", value="UZS (сум)"),
                    SystemSetting(key="default_language", value="ru"),
                    SystemSetting(key="is_sandbox", value="true"),
                    SystemSetting(key="payme_merchant_id", value="64d2910a9b3c4e5f6a7b8c9d"),
                    SystemSetting(key="payme_key", value="m$iL&@4!sK7#pQ9%wZ3*xY1"),
                    SystemSetting(key="click_merchant_id", value="184920"),
                    SystemSetting(key="click_service_id", value="39201"),
                    SystemSetting(key="click_secret_key", value="cLiCk_S3cr3t_K3y_2026"),
                    # Dictionary keys defaults
                    SystemSetting(key="dict_welcome_ru", value="👋 Здравствуйте! Добро пожаловать в Академию Курсов."),
                    SystemSetting(key="dict_welcome_uz_latn", value="👋 Assalomu alaykum! Kurslar Akademiyasiga xush kelibsiz."),
                    SystemSetting(key="dict_welcome_uz_cyrl", value="👋 Ассалому алайкум! Курслар Академиясига хуш келибсиз."),
                    SystemSetting(key="dict_catalog_btn_ru", value="📚 Каталог курсов"),
                    SystemSetting(key="dict_catalog_btn_uz_latn", value="📚 Kurslar katalogi"),
                    SystemSetting(key="dict_catalog_btn_uz_cyrl", value="📚 Курслар каталоги"),
                    SystemSetting(key="dict_profile_btn_ru", value="👤 Личный кабинет"),
                    SystemSetting(key="dict_profile_btn_uz_latn", value="👤 Shaxsiy kabinet"),
                    SystemSetting(key="dict_profile_btn_uz_cyrl", value="👤 Шахсий кабинет"),
                ]
                session.add_all(default_settings)
                await session.flush()

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
                    image_url="https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=800&q=80",
                    telegram_channel_title="Закрытый канал: Python Pro 2026",
                    is_published=True
                )
                c2 = Course(
                    category_id=cat2.id,
                    title="Figma & UX/UI Дизайн 2026",
                    description="Освойте профессию веб-дизайнера: проектирование интерфейсов, мобильные приложения, дизайн-системы.",
                    price_uzs=450000,
                    author="Мария Соколова",
                    image_url="https://images.unsplash.com/photo-1581291518633-83b4ebd1d83e?auto=format&fit=crop&w=800&q=80",
                    telegram_channel_title="Закрытый клуб Figma Masters",
                    is_published=True
                )
                session.add_all([c1, c2])
                await session.commit()
        except Exception as e:
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
