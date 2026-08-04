"""
FastAPI Router for Payme, Click and Telegram Webhooks
"""
from fastapi import APIRouter, Request, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database.session import get_db
from app.payments.payme import PaymeService
from app.payments.click import ClickService
from app.bot.main import dp, bot
from aiogram.types import Update

router = APIRouter()


@router.post("/payments/payme")
async def payme_webhook(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Payme Merchant JSON-RPC endpoint"""
    data = await request.json()
    service = PaymeService(db)
    result = await service.handle_request(data, authorization)
    return result


@router.post("/payments/click")
async def click_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Click Merchant POST protocol endpoint"""
    form_data = await request.form()
    data_dict = dict(form_data)
    service = ClickService(db)
    result = await service.handle_request(data_dict)
    return result


@router.post("/bot/webhook")
async def bot_webhook(request: Request):
    """Telegram Bot Webhook Endpoint"""
    update_data = await request.json()
    update = Update.model_validate(update_data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}
