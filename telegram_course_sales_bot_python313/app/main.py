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
    await init_db()
    
    # Setup Telegram Bot Webhook or Polling
    if settings.USE_WEBHOOK:
        webhook_url = f"{settings.APP_URL}/api/v1/bot/webhook"
        logger.info(f"Setting bot webhook to: {webhook_url}")
        await bot.set_webhook(webhook_url, secret_token=settings.WEBHOOK_SECRET)
    else:
        logger.info("Starting bot in polling mode (background task)...")
        asyncio.create_task(dp.start_polling(bot))
        
    await setup_bot_commands(bot)
    yield
    
    # Shutdown
    logger.info("Shutting down application resources...")
    if settings.USE_WEBHOOK:
        await bot.delete_webhook()
    await bot.session.close()
    await close_db()


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
