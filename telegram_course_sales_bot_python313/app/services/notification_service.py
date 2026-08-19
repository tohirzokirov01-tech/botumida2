"""
Telegram Group Notification Service
Formats and sends sales alerts to the dynamic Group ID stored in SystemSettings table.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from aiogram import Bot

from app.config.settings import settings
from app.database.models import SystemSetting

logger = logging.getLogger(__name__)


async def get_admin_group_id(db: AsyncSession) -> str:
    """Fetch admin group ID dynamically from system_settings table, fallback to env"""
    stmt = select(SystemSetting).where(SystemSetting.key == "admin_group_id")
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()
    if setting and setting.value:
        return setting.value
    return settings.DEFAULT_ADMIN_GROUP_ID


async def send_sale_notification_to_group(
    user_name: str,
    user_phone: str,
    course_title: str,
    amount_uzs: int,
    payment_method: str,
    paid_time: str,
    db: AsyncSession
):
    """
    Sends sales and manual grant notification to admin group
    """
    group_id = await get_admin_group_id(db)

    formatted_amount = f"{amount_uzs:,}".replace(",", " ")

    if "Ручн" in payment_method or "Admin" in payment_method or "manual" in str(payment_method).lower():
        badge_header = "👑 <b>Ручная выдача доступа (Админ)</b>"
    else:
        badge_header = "💰 <b>Новая продажа</b>"

    message_text = (
        f"{badge_header}\n\n"
        f"👤 <b>Пользователь:</b> {user_name}\n"
        f"📞 <b>Телефон:</b> {user_phone}\n"
        f"📚 <b>Курс:</b> "{course_title}"\n"
        f"💵 <b>Сумма:</b> {formatted_amount} сум\n"
        f"💳 <b>Способ:</b> {payment_method}\n"
        f"🕒 <b>Время:</b> {paid_time}"
    )

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=group_id,
            text=message_text,
            parse_mode="HTML"
        )
        logger.info(f"Notification successfully sent to Telegram group {group_id}")
    except Exception as e:
        logger.error(f"Failed to send telegram notification to group {group_id}: {e}")
    finally:
        await bot.session.close()
