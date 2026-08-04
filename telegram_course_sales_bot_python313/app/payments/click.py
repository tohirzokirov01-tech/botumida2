"""
Click Merchant API Protocol Handler (Prepare & Complete Actions)
Verifies MD5 Signature: md5(click_trans_id + service_id + secret_key + merchant_trans_id + amount + action + sign_time)
"""
import hashlib
import logging
from typing import Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config.settings import settings
from app.database.models import Order, OrderStatus

logger = logging.getLogger(__name__)

# Click Error Codes
CLICK_SUCCESS = 0
CLICK_ERROR_SIGN_CHECK_FAILED = -1
CLICK_ERROR_INVALID_AMOUNT = -2
CLICK_ERROR_ACTION_NOT_FOUND = -3
CLICK_ERROR_ALREADY_PAID = -4
CLICK_ERROR_USER_NOT_FOUND = -5
CLICK_ERROR_TRANSACTION_NOT_FOUND = -6


class ClickService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def verify_signature(self, data: Dict[str, Any]) -> bool:
        click_trans_id = str(data.get("click_trans_id", ""))
        service_id = str(data.get("service_id", ""))
        merchant_trans_id = str(data.get("merchant_trans_id", ""))
        merchant_prepare_id = str(data.get("merchant_prepare_id", "")) if data.get("action") == "1" else ""
        amount = str(data.get("amount", ""))
        action = str(data.get("action", ""))
        sign_time = str(data.get("sign_time", ""))
        sign_string = str(data.get("sign_string", ""))

        secret_key = settings.CLICK_SECRET_KEY

        # Check hash calculation
        if action == "0": # Prepare
            raw_str = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}{amount}{action}{sign_time}"
        else: # Complete
            raw_str = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}{merchant_prepare_id}{amount}{action}{sign_time}"

        calc_sign = hashlib.md5(raw_str.encode("utf-8")).hexdigest()
        return calc_sign.lower() == sign_string.lower()

    async def handle_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        action = str(data.get("action"))

        # Verify Signature
        if not self.verify_signature(data):
            return {
                "error": CLICK_ERROR_SIGN_CHECK_FAILED,
                "error_note": "SIGN CHECK FAILED"
            }

        if action == "0":
            return await self.prepare(data)
        elif action == "1":
            return await self.complete(data)
        else:
            return {"error": CLICK_ERROR_ACTION_NOT_FOUND, "error_note": "Action not found"}

    async def prepare(self, data: Dict[str, Any]) -> Dict[str, Any]:
        order_number = data.get("merchant_trans_id")
        amount = float(data.get("amount", 0))

        stmt = select(Order).where(Order.order_number == order_number)
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()

        if not order:
            return {"error": CLICK_ERROR_USER_NOT_FOUND, "error_note": "Order not found"}

        if float(order.amount_uzs) != amount:
            return {"error": CLICK_ERROR_INVALID_AMOUNT, "error_note": "Incorrect amount"}

        if order.status == OrderStatus.PAID:
            return {"error": CLICK_ERROR_ALREADY_PAID, "error_note": "Already paid"}

        return {
            "error": CLICK_SUCCESS,
            "error_note": "Success",
            "click_trans_id": data.get("click_trans_id"),
            "merchant_trans_id": order_number,
            "merchant_prepare_id": str(order.id)
        }

    async def complete(self, data: Dict[str, Any]) -> Dict[str, Any]:
        order_number = data.get("merchant_trans_id")
        click_trans_id = str(data.get("click_trans_id"))
        error_code = int(data.get("error", 0))

        stmt = select(Order).where(Order.order_number == order_number)
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()

        if not order:
            return {"error": CLICK_ERROR_TRANSACTION_NOT_FOUND, "error_note": "Order not found"}

        if error_code < 0:
            order.status = OrderStatus.CANCELLED
            await self.db.commit()
            return {"error": CLICK_SUCCESS, "error_note": "Cancelled due to provider error"}

        if order.status == OrderStatus.PAID:
            return {
                "error": CLICK_SUCCESS,
                "error_note": "Already paid",
                "click_trans_id": click_trans_id,
                "merchant_trans_id": order_number,
                "merchant_confirm_id": str(order.id)
            }

        order.status = OrderStatus.PAID
        order.transaction_id = click_trans_id
        order.paid_at = datetime.utcnow()
        await self.db.commit()

        # Trigger automatic fulfillment and Telegram sale notification
        from app.payments.service import on_payment_success
        await on_payment_success(order, payment_method="Click", db=self.db)

        return {
            "error": CLICK_SUCCESS,
            "error_note": "Success",
            "click_trans_id": click_trans_id,
            "merchant_trans_id": order_number,
            "merchant_confirm_id": str(order.id)
        }
