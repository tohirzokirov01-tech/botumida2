"""
Payment Processor Orchestrator
Grants course access to user, records receipt, and triggers Telegram Group sale notification.
"""
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import Order, User, Course, UserCourseAccess, SystemLog
from app.services.notification_service import send_sale_notification_to_group

logger = logging.getLogger(__name__)


async def on_payment_success(order: Order, payment_method: str, db: AsyncSession):
    """
    Callback invoked automatically after Payme/Click webhook completes payment.
    """
    logger.info(f"Payment completed for Order {order.order_number} via {payment_method}")

    # 1. Grant course access if not granted already
    stmt = select(UserCourseAccess).where(
        UserCourseAccess.user_id == order.user_id,
        UserCourseAccess.course_id == order.course_id
    )
    res = await db.execute(stmt)
    existing_access = res.scalar_one_or_none()

    if not existing_access:
        access = UserCourseAccess(
            user_id=order.user_id,
            course_id=order.course_id,
            granted_by=f"payment_{payment_method.lower()}"
        )
        db.add(access)

    # 2. Fetch User & Course details for Notification
    user_stmt = select(User).where(User.id == order.user_id)
    u_res = await db.execute(user_stmt)
    user = u_res.scalar_one_or_none()

    course_stmt = select(Course).where(Course.id == order.course_id)
    c_res = await db.execute(course_stmt)
    course = c_res.scalar_one_or_none()

    # 3. System Logging
    log_entry = SystemLog(
        level="INFO",
        source=f"{payment_method}Webhook",
        message=f"Успешная оплата заказа {order.order_number} на сумму {order.amount_uzs:,} UZS.",
        details=f"User: {user.first_name if user else 'N/A'} (ID: {order.user_id}) | Course: {course.title if course else 'N/A'}"
    )
    db.add(log_entry)
    await db.commit()

    # 4. Generate Single-Use Telegram Channel Invite Link (member_limit=1)
    invite_link = None
    if course and course.telegram_channel_id:
        try:
            from app.bot.main import bot
            invite = await bot.create_chat_invite_link(
                chat_id=int(course.telegram_channel_id),
                name=f"Course: {course.title[:15]} | User: {user.telegram_id if user else order.user_id}",
                member_limit=1,  # CRITICAL: Unique single-use invite link for 1 person!
                creates_join_request=False
            )
            invite_link = invite.invite_link
            order.invite_link = invite_link
            order.invite_link_used = False
            order.invite_link_limit = 1
            await db.commit()
            
            # Direct message to User with unique 1-person channel link
            if user and user.telegram_id:
                msg_text = (
                    f"🎉 <b>Оплата прошла успешно!</b>\n\n"
                    f"Вам открыт доступ к курсу <b>{course.title}</b>!\n\n"
                    f"🔒 <b>Персональная одноразовая ссылка в закрытый канал:</b>\n"
                    f"📍 <i>{course.telegram_channel_title or 'Закрытый канал курса'}</i>\n"
                    f"🎫 <i>Лимит: 1 вход (member_limit=1)</i>\n"
                    f"🔗 {invite_link}\n\n"
                    f"⚠️ <i>Ссылка сгенерирована специально для вас и аннулируется после первого перехода.</i>"
                )
                await bot.send_message(chat_id=user.telegram_id, text=msg_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to create single-use chat invite link: {e}")

    # 5. Send automatic Telegram Notification to Admin Group ID
    if user and course:
        user_display = f"{user.first_name} {user.last_name or ''}".strip()
        await send_sale_notification_to_group(
            user_name=user_display,
            user_phone=user.phone or "Н/У",
            course_title=course.title,
            amount_uzs=order.amount_uzs,
            payment_method=payment_method,
            paid_time=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            db=db
        )
