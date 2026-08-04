"""
Payme Merchant JSON-RPC Protocol Handler
Implements CheckPerformTransaction, CreateTransaction, PerformTransaction, CancelTransaction, CheckTransaction.
Handles authorization header basic base64 check and UzSUM to tiyin conversion (1 UZS = 100 tiyin).
"""
import base64
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config.settings import settings
from app.database.models import Order, OrderStatus

logger = logging.getLogger(__name__)

# Payme JSON-RPC Error Codes
PAYME_ERROR_INVALID_AMOUNT = -31001
PAYME_ERROR_ORDER_NOT_FOUND = -31050
PAYME_ERROR_TRANSACTION_NOT_FOUND = -31003
PAYME_ERROR_COULD_NOT_PERFORM = -31008
PAYME_ERROR_ALREADY_DONE = -31007
PAYME_ERROR_AUTH_FAILED = -32504


class PaymeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def verify_auth(self, auth_header: Optional[str]) -> bool:
        if not auth_header or not auth_header.startswith("Basic "):
            return False
        encoded = auth_header.replace("Basic ", "")
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
            login, secret = decoded.split(":")
            # Support both live and test keys
            return secret in [settings.PAYME_KEY, settings.PAYME_TEST_KEY]
        except Exception:
            return False

    async def handle_request(self, data: Dict[str, Any], auth_header: Optional[str]) -> Dict[str, Any]:
        if not self.verify_auth(auth_header):
            return {
                "error": {
                    "code": PAYME_ERROR_AUTH_FAILED,
                    "message": {"ru": "Ошибка авторизации", "uz": "Avtorizatsiya xatosi"}
                },
                "id": data.get("id")
            }

        method = data.get("method")
        params = data.get("params", {})
        request_id = data.get("id")

        if method == "CheckPerformTransaction":
            res = await self.check_perform_transaction(params)
        elif method == "CreateTransaction":
            res = await self.create_transaction(params)
        elif method == "PerformTransaction":
            res = await self.perform_transaction(params)
        elif method == "CancelTransaction":
            res = await self.cancel_transaction(params)
        elif method == "CheckTransaction":
            res = await self.check_transaction(params)
        else:
            res = {"error": {"code": -32601, "message": "Method not found"}}

        res["id"] = request_id
        return res

    async def check_perform_transaction(self, params: Dict[str, Any]) -> Dict[str, Any]:
        account = params.get("account", {})
        order_number = account.get("order_number")
        amount_tiyin = params.get("amount", 0)

        order = await self._get_order_by_number(order_number)
        if not order:
            return {
                "error": {
                    "code": PAYME_ERROR_ORDER_NOT_FOUND,
                    "message": {"ru": "Заказ не найден", "uz": "Buyurtma topilmadi"}
                }
            }

        expected_tiyin = order.amount_uzs * 100
        if amount_tiyin != expected_tiyin:
            return {
                "error": {
                    "code": PAYME_ERROR_INVALID_AMOUNT,
                    "message": {"ru": "Неверная сумма платежа", "uz": "Noto'g'ri summa"}
                }
            }

        return {"result": {"allow": True}}

    async def create_transaction(self, params: Dict[str, Any]) -> Dict[str, Any]:
        payme_trans_id = params.get("id")
        account = params.get("account", {})
        order_number = account.get("order_number")

        order = await self._get_order_by_number(order_number)
        if not order:
            return {"error": {"code": PAYME_ERROR_ORDER_NOT_FOUND, "message": {"ru": "Заказ не найден"}}}

        # Update order with payme trans id
        order.transaction_id = payme_trans_id
        await self.db.commit()

        create_time = int(datetime.utcnow().timestamp() * 1000)
        return {
            "result": {
                "create_time": create_time,
                "transaction": str(order.id),
                "state": 1
            }
        }

    async def perform_transaction(self, params: Dict[str, Any]) -> Dict[str, Any]:
        payme_trans_id = params.get("id")
        stmt = select(Order).where(Order.transaction_id == payme_trans_id)
        result = await self.db.execute(stmt)
        order = result.scalar_one_or_none()

        if not order:
            return {"error": {"code": PAYME_ERROR_TRANSACTION_NOT_FOUND, "message": {"ru": "Транзакция не найдена"}}}

        if order.status == OrderStatus.PAID:
            perform_time = int(order.paid_at.timestamp() * 1000) if order.paid_at else int(datetime.utcnow().timestamp() * 1000)
            return {
                "result": {
                    "transaction": str(order.id),
                    "perform_time": perform_time,
                    "state": 2
                }
            }

        order.status = OrderStatus.PAID
        order.paid_at = datetime.utcnow()
        await self.db.commit()

        # Trigger background delivery & notification
        from app.payments.service import on_payment_success
        await on_payment_success(order, payment_method="Payme", db=self.db)

        perform_time = int(order.paid_at.timestamp() * 1000)
        return {
            "result": {
                "transaction": str(order.id),
                "perform_time": perform_time,
                "state": 2
            }
        }

    async def cancel_transaction(self, params: Dict[str, Any]) -> Dict[str, Any]:
        payme_trans_id = params.get("id")
        reason = params.get("reason", 1)
        
        stmt = select(Order).where(Order.transaction_id == payme_trans_id)
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()

        if not order:
            return {"error": {"code": PAYME_ERROR_TRANSACTION_NOT_FOUND, "message": {"ru": "Транзакция не найдена"}}}

        order.status = OrderStatus.CANCELLED
        await self.db.commit()
        cancel_time = int(datetime.utcnow().timestamp() * 1000)

        return {
            "result": {
                "transaction": str(order.id),
                "cancel_time": cancel_time,
                "state": -1
            }
        }

    async def check_transaction(self, params: Dict[str, Any]) -> Dict[str, Any]:
        payme_trans_id = params.get("id")
        stmt = select(Order).where(Order.transaction_id == payme_trans_id)
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()

        if not order:
            return {"error": {"code": PAYME_ERROR_TRANSACTION_NOT_FOUND, "message": {"ru": "Транзакция не найдена"}}}

        state = 2 if order.status == OrderStatus.PAID else ( -1 if order.status == OrderStatus.CANCELLED else 1 )
        create_time = int(order.created_at.timestamp() * 1000)
        perform_time = int(order.paid_at.timestamp() * 1000) if order.paid_at else 0

        return {
            "result": {
                "create_time": create_time,
                "perform_time": perform_time,
                "cancel_time": 0,
                "transaction": str(order.id),
                "state": state,
                "reason": None
            }
        }

    async def _get_order_by_number(self, order_number: str) -> Optional[Order]:
        stmt = select(Order).where(Order.order_number == order_number)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
