"""
Production Entry Point for Telegram Online Course Bot & FastAPI Admin
Runs FastAPI web application, Webhook endpoints for Payme & Click, and aiogram 3 Bot dispatcher.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config.settings import settings
from app.database.session import init_db, close_db
from app.api.webhooks import router as webhooks_router
from app.admin.router import router as admin_router
from app.bot.main import bot, dp, setup_bot_commands

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Database connection pool...")
    try:
        await init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}. Check DATABASE_URL in Railway.")

    # Setup Telegram Bot Webhook or Polling
    try:
        clean_token = settings.CLEAN_BOT_TOKEN
        if not clean_token or "AAH_x92JkL0mN81qZ" in clean_token:
            logger.warning("⚠️ BOT_TOKEN is missing or using default dummy value! Please set BOT_TOKEN in Railway Variables without quotes.")
        else:
            bot_me = await bot.get_me()
            logger.info(f"🤖 Connected to Telegram as @{bot_me.username} ({bot_me.first_name})")
            if settings.USE_WEBHOOK:
                webhook_url = f"{settings.CLEAN_APP_URL}/api/v1/bot/webhook"
                logger.info(f"Setting bot webhook to: {webhook_url}")
                await bot.set_webhook(webhook_url, secret_token=settings.WEBHOOK_SECRET)
            else:
                logger.info("Starting bot in long-polling mode...")
                await bot.delete_webhook(drop_pending_updates=True)
                asyncio.create_task(dp.start_polling(bot))
                
            await setup_bot_commands(bot)
            logger.info("🚀 Telegram Bot initialized and polling started successfully.")
    except Exception as e:
        logger.error(f"❌ Telegram Bot startup failed: {e}. Make sure BOT_TOKEN is valid from @BotFather in Railway Variables.")

    yield
    
    # Shutdown
    logger.info("Shutting down application resources...")
    try:
        if settings.USE_WEBHOOK and settings.BOT_TOKEN:
            await bot.delete_webhook()
        await bot.session.close()
        await close_db()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


app = FastAPI(
    title="Telegram Course Sales Bot API & Admin Panel",
    description="Backend service with Payme/Click Webhooks, aiogram 3 integration and FastAPI Admin Panel",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/admin", tags=["Admin Panel"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT, "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
