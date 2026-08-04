"""
aiogram 3 Bot Initialization & Dispatcher Setup
"""
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from app.config.settings import settings
from app.bot.handlers import start, catalog
from app.bot.middlewares.db import DbSessionMiddleware

logger = logging.getLogger(__name__)

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

# Register DB session middleware to inject 'db' AsyncSession into handlers
dp.update.outer_middleware(DbSessionMiddleware())

# Register Handler Routers
dp.include_router(start.router)
dp.include_router(catalog.router)


async def setup_bot_commands(bot_instance: Bot):
    from aiogram.types import BotCommand
    commands = [
        BotCommand(command="start", description="🚀 Перезапустить бота / Главное меню"),
        BotCommand(command="catalog", description="📚 Каталог онлайн-курсов"),
    ]
    try:
        await bot_instance.set_my_commands(commands)
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")
