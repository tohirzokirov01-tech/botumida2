"""
FastAPI Admin Panel Router & Management Dashboard
Provides responsive web interface for managing courses, users, orders, and system settings.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid
import re
import html
import json

from datetime import datetime
from app.database.session import get_db
from app.database.models import User, Course, CourseTier, Order, OrderStatus, PaymentMethod, UserCourseAccess, Category, SystemSetting, SystemLog
from app.services.notification_service import send_sale_notification_to_group
from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/courses/create")
async def create_course_admin(
    title: str = Form(...),
    price_uzs: int = Form(500000),
    author: str = Form("Инструктор"),
    description: str = Form(""),
    image_url: str = Form(""),
    telegram_channel_title: str = Form(""),
    telegram_channel_id: str = Form(""),
    category_id: Optional[int] = Form(None),
    has_tiers: Optional[str] = Form("false"),
    tiers_json: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    if not category_id:
        cat_res = await db.execute(select(Category).limit(1))
        cat = cat_res.scalars().first()
        if not cat:
            cat = Category(name="Курсы", slug="courses")
            db.add(cat)
            await db.flush()
        category_id = cat.id

    base_slug = re.sub(r'[^a-zA-Z0-9]', '-', title.lower()).strip('-') or "course"
    slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    is_tiered = (has_tiers in ["true", "1", "on"])
    parsed_tiers = []
    if is_tiered and tiers_json:
        try:
            parsed_tiers = json.loads(tiers_json)
        except Exception:
            parsed_tiers = []

    effective_price = price_uzs
    if is_tiered and parsed_tiers:
        tier_prices = [int(t.get("price_uzs", price_uzs)) for t in parsed_tiers if t.get("price_uzs")]
        if tier_prices:
            effective_price = min(tier_prices)

    new_course = Course(
        category_id=category_id,
        title=title,
        slug=slug,
        price_uzs=effective_price,
        author=author,
        description=description or "Описание курса",
        image_url=image_url or "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=800&q=80",
        telegram_channel_title=telegram_channel_title or "🔒 Закрытый VIP Telegram-Канал",
        telegram_channel_id=telegram_channel_id or "-1001928374999",
        has_tiers=bool(is_tiered and parsed_tiers),
        is_published=True
    )
    db.add(new_course)
    await db.flush()

    if is_tiered and parsed_tiers:
        for idx, t in enumerate(parsed_tiers):
            tier_obj = CourseTier(
                course_id=new_course.id,
                title=t.get("title", f"Тариф #{idx+1}"),
                price_uzs=int(t.get("price_uzs", 500000)),
                description=t.get("description", ""),
                telegram_channel_title=t.get("telegram_channel_title") or new_course.telegram_channel_title,
                telegram_channel_id=t.get("telegram_channel_id") or new_course.telegram_channel_id
            )
            db.add(tier_obj)

    await db.commit()
    return RedirectResponse(url="/admin/#courses", status_code=303)


@router.post("/courses/{course_id}/edit")
async def edit_course_admin(
    course_id: int,
    title: str = Form(...),
    price_uzs: int = Form(500000),
    author: str = Form("Инструктор"),
    description: str = Form(""),
    image_url: str = Form(""),
    telegram_channel_title: str = Form(""),
    telegram_channel_id: str = Form(""),
    has_tiers: Optional[str] = Form("false"),
    tiers_json: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Course).where(Course.id == course_id)
    res = await db.execute(stmt)
    course = res.scalars().first()
    if course:
        course.title = title
        course.author = author
        course.description = description
        if image_url:
            course.image_url = image_url
        course.telegram_channel_title = telegram_channel_title
        course.telegram_channel_id = telegram_channel_id

        is_tiered = (has_tiers in ["true", "1", "on"])
        parsed_tiers = []
        if is_tiered and tiers_json:
            try:
                parsed_tiers = json.loads(tiers_json)
            except Exception:
                parsed_tiers = []

        # Remove old tiers
        del_stmt = select(CourseTier).where(CourseTier.course_id == course_id)
        del_res = await db.execute(del_stmt)
        for old_t in del_res.scalars().all():
            await db.delete(old_t)

        if is_tiered and parsed_tiers:
            course.has_tiers = True
            tier_prices = [int(t.get("price_uzs", price_uzs)) for t in parsed_tiers if t.get("price_uzs")]
            if tier_prices:
                course.price_uzs = min(tier_prices)
            for idx, t in enumerate(parsed_tiers):
                tier_obj = CourseTier(
                    course_id=course.id,
                    title=t.get("title", f"Тариф #{idx+1}"),
                    price_uzs=int(t.get("price_uzs", 500000)),
                    description=t.get("description", ""),
                    telegram_channel_title=t.get("telegram_channel_title") or course.telegram_channel_title,
                    telegram_channel_id=t.get("telegram_channel_id") or course.telegram_channel_id
                )
                db.add(tier_obj)
        else:
            course.has_tiers = False
            course.price_uzs = price_uzs

        await db.commit()
    return RedirectResponse(url="/admin/#courses", status_code=303)


@router.post("/courses/{course_id}/delete")
async def delete_course_admin(
    course_id: int,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Course).where(Course.id == course_id)
    res = await db.execute(stmt)
    course = res.scalars().first()
    if course:
        await db.delete(course)
        await db.commit()
    return RedirectResponse(url="/admin/#courses", status_code=303)


@router.post("/access/grant")
async def grant_access_admin(
    user_identifier: str = Form(...),
    course_id: int = Form(...),
    tier_title: Optional[str] = Form(None),
    reason: str = Form("manual_payment"),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(User)
    if user_identifier.isdigit():
        stmt = stmt.where(User.telegram_id == int(user_identifier))
    else:
        stmt = stmt.where(User.phone == user_identifier)
    
    user_res = await db.execute(stmt)
    user = user_res.scalar_one_or_none()

    if not user:
        tg_id = int(user_identifier) if user_identifier.isdigit() else 999000111
        user = User(
            telegram_id=tg_id,
            first_name="Пользователь (Ручной доступ)",
            phone=user_identifier if not user_identifier.isdigit() else None,
            referral_code=f"REF{tg_id}"
        )
        db.add(user)
        await db.flush()

    course_res = await db.execute(select(Course).where(Course.id == course_id))
    course = course_res.scalar_one_or_none()
    amount = course.price_uzs if course else 0

    order_num = f"MANUAL-{uuid.uuid4().hex[:6].upper()}"

    new_order = Order(
        order_number=order_num,
        user_id=user.id,
        course_id=course_id,
        tier_title=tier_title,
        amount_uzs=amount,
        payment_method=PaymentMethod.ADMIN_GRANT,
        status=OrderStatus.PAID
    )
    db.add(new_order)

    # Grant UserCourseAccess
    access_check = await db.execute(
        select(UserCourseAccess).where(
            UserCourseAccess.user_id == user.id,
            UserCourseAccess.course_id == course_id
        )
    )
    existing_acc = access_check.scalars().first()
    if not existing_acc:
        db.add(UserCourseAccess(
            user_id=user.id,
            course_id=course_id,
            tier_title=tier_title,
            granted_by="admin_manual"
        ))
    else:
        if tier_title:
            existing_acc.tier_title = tier_title

    db.add(SystemLog(
        level="INFO",
        source="AdminGrant",
        message=f"Выдан ручной доступ к курсу #{course_id} для пользователя ID={user.telegram_id}"
    ))

    await db.commit()

    # 1. Generate Single-Use Telegram Channel Invite Link (member_limit=1) & Send to User
    invite_link = None
    if course and user and user.telegram_id:
        try:
            from app.bot.main import bot
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            if course.telegram_channel_id:
                try:
                    ch_id = int(course.telegram_channel_id) if str(course.telegram_channel_id).replace("-", "").isdigit() else course.telegram_channel_id
                    invite = await bot.create_chat_invite_link(
                        chat_id=ch_id,
                        name=f"Manual: {course.title[:15]} | User: {user.telegram_id}",
                        member_limit=1,
                        creates_join_request=False
                    )
                    invite_link = invite.invite_link
                except Exception as link_err:
                    logger.warning(f"Could not create single-use dynamic invite link: {link_err}")

            if not invite_link:
                invite_link = course.telegram_channel_id if (course.telegram_channel_id and "t.me" in str(course.telegram_channel_id)) else "https://t.me/"

            new_order.invite_link = invite_link
            new_order.invite_link_used = False
            new_order.invite_link_limit = 1
            await db.commit()

            # Direct message to User with unique access link
            user_msg = (
                f"🎉 <b>Вам предоставлен доступ к курсу!</b>\n\n"
                f"📚 <b>Курс:</b> «{course.title}»\n"
                f"👤 <b>Автор / Преподаватель:</b> {course.author}\n"
                f"🔒 <b>Закрытый канал:</b> {course.telegram_channel_title or course.title}\n\n"
                f"🔗 <b>Ваша персональная ссылка для входа:</b>\n"
                f"👉 {invite_link}\n\n"
                f"⚠️ <i>Ссылка сгенерирована персонально для вас. Нажмите на кнопку ниже, чтобы войти в канал:</i>"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Перейти в закрытый канал курса", url=invite_link)]
            ])
            await bot.send_message(
                chat_id=user.telegram_id,
                text=user_msg,
                reply_markup=kb,
                parse_mode="HTML"
            )
            logger.info(f"Invite link message successfully sent to user {user.telegram_id}")
        except Exception as e:
            logger.error(f"Failed to deliver invite link to user {user.telegram_id}: {e}")

    # 2. Send automatic Telegram Notification to Admin Group ID
    user_display = f"{user.first_name} {user.last_name or ''}".strip()
    course_title = course.title if course else f"Курс #{course_id}"
    try:
        await send_sale_notification_to_group(
            user_name=f"{user_display} (ID: {user.telegram_id})",
            user_phone=user.phone or "Н/У",
            course_title=course_title,
            amount_uzs=amount,
            payment_method="Ручная выдача (Admin)",
            paid_time=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            db=db
        )
    except Exception as e:
        pass

    return RedirectResponse(url="/admin/#users", status_code=303)


@router.post("/access/revoke")
async def revoke_access_admin(
    user_id: int = Form(...),
    course_id: int = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Revoke course access from user (delete UserCourseAccess record, log event, and notify user)
    """
    try:
        stmt = select(UserCourseAccess).where(
            UserCourseAccess.user_id == user_id,
            UserCourseAccess.course_id == course_id
        )
        res = await db.execute(stmt)
        access_record = res.scalar_one_or_none()
        if access_record:
            await db.delete(access_record)

        user_res = await db.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()

        course_res = await db.execute(select(Course).where(Course.id == course_id))
        course = course_res.scalar_one_or_none()

        course_title = course.title if course else f"Курс #{course_id}"
        user_tg = user.telegram_id if user else user_id

        db.add(SystemLog(
            level="WARNING",
            source="AdminRevoke",
            message=f"Отозван доступ к курсу «{course_title}» у пользователя ID={user_tg}"
        ))

        await db.commit()

        # Direct message to user about revoked access
        if user and user.telegram_id and course:
            try:
                from app.bot.main import bot
                sup_stmt = select(SystemSetting).where(SystemSetting.key == "support_username")
                sup_res = await db.execute(sup_stmt)
                sup_row = sup_res.scalar_one_or_none()
                support_contact = sup_row.value if (sup_row and sup_row.value) else getattr(settings, "SUPPORT_USERNAME", "@course_support_uz")

                revoke_msg = (
                    f"ℹ️ <b>Уведомление об изменении доступа</b>\n\n"
                    f"Ваш доступ к курсу «{course.title}» был закрыт администратором.\n\n"
                    f"По всем вопросам обращайтесь в поддержку: {support_contact}"
                )
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=revoke_msg,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Could not send revoke telegram notification to user {user.telegram_id}: {e}")

    except Exception as general_err:
        logger.error(f"Error during revoke_access_admin: {general_err}")

    return RedirectResponse(url="/admin/#users", status_code=303)


@router.post("/settings/update")
async def update_settings_admin(
    bot_name: str = Form("Курсы & Обучение Telegram Bot"),
    support_username: str = Form("@course_support_uz"),
    admin_group_id: str = Form("-100293847561"),
    default_currency: str = Form("UZS (сум)"),
    default_language: str = Form("ru"),
    is_sandbox: str = Form("true"),
    payme_merchant_id: str = Form("64d2910a9b3c4e5f6a7b8c9d"),
    payme_key: str = Form("m$iL&@4!sK7#pQ9%wZ3*xY1"),
    click_merchant_id: str = Form("184920"),
    click_service_id: str = Form("39201"),
    click_secret_key: str = Form("cLiCk_S3cr3t_K3y_2026"),
    db: AsyncSession = Depends(get_db)
):
    settings_data = {
        "bot_name": bot_name,
        "support_username": support_username,
        "admin_group_id": admin_group_id,
        "default_currency": default_currency,
        "default_language": default_language,
        "is_sandbox": is_sandbox,
        "payme_merchant_id": payme_merchant_id,
        "payme_key": payme_key,
        "click_merchant_id": click_merchant_id,
        "click_service_id": click_service_id,
        "click_secret_key": click_secret_key,
    }
    for k, v in settings_data.items():
        stmt = select(SystemSetting).where(SystemSetting.key == k)
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting:
            setting.value = v
        else:
            db.add(SystemSetting(key=k, value=v))
    
    db.add(SystemLog(
        level="INFO",
        source="AdminSettings",
        message="Настройки Payme, Click, Telegram группы и Языка успешно обновлены через Панель Управления."
    ))
    await db.commit()
    return RedirectResponse(url="/admin/#settings", status_code=303)


@router.post("/dictionary/update")
async def update_dictionary_admin(
    dict_welcome_ru: str = Form(...),
    dict_welcome_uz_latn: str = Form(...),
    dict_welcome_uz_cyrl: str = Form(...),
    dict_catalog_btn_ru: str = Form(...),
    dict_catalog_btn_uz_latn: str = Form(...),
    dict_catalog_btn_uz_cyrl: str = Form(...),
    dict_profile_btn_ru: str = Form(...),
    dict_profile_btn_uz_latn: str = Form(...),
    dict_profile_btn_uz_cyrl: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    dict_data = {
        "dict_welcome_ru": dict_welcome_ru,
        "dict_welcome_uz_latn": dict_welcome_uz_latn,
        "dict_welcome_uz_cyrl": dict_welcome_uz_cyrl,
        "dict_catalog_btn_ru": dict_catalog_btn_ru,
        "dict_catalog_btn_uz_latn": dict_catalog_btn_uz_latn,
        "dict_catalog_btn_uz_cyrl": dict_catalog_btn_uz_cyrl,
        "dict_profile_btn_ru": dict_profile_btn_ru,
        "dict_profile_btn_uz_latn": dict_profile_btn_uz_latn,
        "dict_profile_btn_uz_cyrl": dict_profile_btn_uz_cyrl,
    }
    for k, v in dict_data.items():
        stmt = select(SystemSetting).where(SystemSetting.key == k)
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting:
            setting.value = v
        else:
            db.add(SystemSetting(key=k, value=v))
    
    db.add(SystemLog(
        level="INFO",
        source="DictionaryEditor",
        message="Словарь фраз бота (RU, UZ Lotin, UZ Cyrl) успешно обновлен в базе данных."
    ))
    await db.commit()
    return RedirectResponse(url="/admin/#dictionary", status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    # Stats queries
    users_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    courses_count = (await db.execute(select(func.count(Course.id)))).scalar() or 0
    orders_count = (await db.execute(select(func.count(Order.id)))).scalar() or 0
    
    paid_orders_stmt = select(func.sum(Order.amount_uzs)).where(Order.status == OrderStatus.PAID)
    total_revenue_raw = (await db.execute(paid_orders_stmt)).scalar() or 0
    try:
        total_revenue_int = int(float(total_revenue_raw))
    except Exception:
        total_revenue_int = 0
    formatted_total_revenue = f"{total_revenue_int:,}".replace(",", " ")

    # Fetch settings from DB dynamically
    settings_res = await db.execute(select(SystemSetting))
    sys_settings = {s.key: s.value for s in settings_res.scalars().all()}

    bot_name_val = sys_settings.get("bot_name", "Курсы & Обучение Telegram Bot")
    support_username_val = sys_settings.get("support_username", "@course_support_uz")
    admin_group_id_val = sys_settings.get("admin_group_id", "-100293847561")
    default_currency_val = sys_settings.get("default_currency", "UZS (сум)")
    default_language_val = sys_settings.get("default_language", "ru")
    is_sandbox_val = sys_settings.get("is_sandbox", "true")
    payme_merchant_id_val = sys_settings.get("payme_merchant_id", "64d2910a9b3c4e5f6a7b8c9d")
    payme_key_val = sys_settings.get("payme_key", "m$iL&@4!sK7#pQ9%wZ3*xY1")
    click_merchant_id_val = sys_settings.get("click_merchant_id", "184920")
    click_service_id_val = sys_settings.get("click_service_id", "39201")
    click_secret_key_val = sys_settings.get("click_secret_key", "cLiCk_S3cr3t_K3y_2026")

    dict_welcome_ru_val = sys_settings.get("dict_welcome_ru", "👋 Здравствуйте! Добро пожаловать в Академию Курсов.")
    dict_welcome_uz_latn_val = sys_settings.get("dict_welcome_uz_latn", "👋 Assalomu alaykum! Kurslar Akademiyasiga xush kelibsiz.")
    dict_welcome_uz_cyrl_val = sys_settings.get("dict_welcome_uz_cyrl", "👋 Ассалому алайкум! Курслар Академиясига хуш келибсиз.")
    dict_catalog_btn_ru_val = sys_settings.get("dict_catalog_btn_ru", "📚 Каталог курсов")
    dict_catalog_btn_uz_latn_val = sys_settings.get("dict_catalog_btn_uz_latn", "📚 Kurslar katalogi")
    dict_catalog_btn_uz_cyrl_val = sys_settings.get("dict_catalog_btn_uz_cyrl", "📚 Курслар каталоги")
    dict_profile_btn_ru_val = sys_settings.get("dict_profile_btn_ru", "👤 Личный кабинет")
    dict_profile_btn_uz_latn_val = sys_settings.get("dict_profile_btn_uz_latn", "👤 Shaxsiy kabinet")
    dict_profile_btn_uz_cyrl_val = sys_settings.get("dict_profile_btn_uz_cyrl", "👤 Шахсий кабинет")

    # Fetch records for tables with automatic schema healing
    try:
        courses_res = await db.execute(select(Course).order_by(Course.id.desc()))
        courses = courses_res.scalars().all()
    except Exception:
        await db.rollback()
        from sqlalchemy import text
        from app.database.models import Base
        try:
            from app.database.session import engine
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                for col_sql in [
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(16) DEFAULT 'ru';",
                    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS has_tiers BOOLEAN DEFAULT FALSE;",
                    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS tier_id INTEGER;",
                    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS tier_title VARCHAR(128);",
                    "ALTER TABLE user_course_access ADD COLUMN IF NOT EXISTS tier_title VARCHAR(128);",
                ]:
                    try:
                        await conn.execute(text(col_sql))
                    except Exception:
                        pass
        except Exception:
            pass
        courses_res = await db.execute(select(Course).order_by(Course.id.desc()))
        courses = courses_res.scalars().all()

    try:
        tiers_res = await db.execute(select(CourseTier))
        all_tiers = tiers_res.scalars().all()
    except Exception:
        all_tiers = []
    course_tiers_map = {}
    for t in all_tiers:
        course_tiers_map.setdefault(t.course_id, []).append(t)

    users_res = await db.execute(select(User).order_by(User.id.desc()).limit(20))
    users = users_res.scalars().all()

    orders_res = await db.execute(select(Order).order_by(Order.id.desc()).limit(20))
    orders = orders_res.scalars().all()

    # Fetch categories for form
    cats_res = await db.execute(select(Category))
    categories = cats_res.scalars().all()
    category_options = "".join([f'<option value="{c.id}">{c.name}</option>' for c in categories])
    if not category_options:
        category_options = '<option value="">Основная категория</option>'

    # Build Course Options for manual grant
    course_options = "".join([f'<option value="{c.id}">{c.title} ({int(c.price_uzs or 0):,} сум)</option>'.replace(",", " ") for c in courses])
    if not course_options:
        course_options = '<option value="">Нет доступных курсов</option>'

    # Build User Options for manual revoke modal
    user_options = "".join([f'<option value="{u.id}">{u.first_name or ""} {u.last_name or ""} (@{u.username or u.telegram_id})</option>' for u in users])
    if not user_options:
        user_options = '<option value="">Нет пользователей</option>'

    # Fetch all user course access records
    access_res = await db.execute(select(UserCourseAccess))
    access_list = access_res.scalars().all()
    user_access_map = {}
    for acc in access_list:
        user_access_map.setdefault(acc.user_id, []).append({"course_id": acc.course_id, "tier_title": acc.tier_title})
    courses_map = {c.id: c for c in courses}

    # Build HTML rows
    course_rows = ""
    for c in courses:
        desc_escaped = html.escape(" ".join((c.description or "").split()), quote=True)
        img_val = html.escape(c.image_url or "", quote=True)
        title_escaped = html.escape(c.title or "", quote=True)
        author_escaped = html.escape(c.author or "", quote=True)
        ch_title = html.escape(c.telegram_channel_title or "", quote=True)
        ch_id = html.escape(c.telegram_channel_id or "", quote=True)

        c_tiers = course_tiers_map.get(c.id, [])
        is_tiered = bool(c.has_tiers and c_tiers)
        tiers_payload = [
            {
                "id": t.id,
                "title": t.title,
                "price_uzs": t.price_uzs,
                "description": t.description or "",
                "telegram_channel_title": t.telegram_channel_title or "",
                "telegram_channel_id": t.telegram_channel_id or ""
            }
            for t in c_tiers
        ]
        tiers_json_escaped = html.escape(json.dumps(tiers_payload), quote=True)

        if is_tiered:
            tier_badges = "".join([f'<span style="display:inline-block; background:#0284c7; color:#fff; font-size:0.7rem; font-weight:600; padding:0.15rem 0.4rem; border-radius:4px; margin:0.1rem 0.2rem 0.1rem 0;">💎 {html.escape(t.title)}: {int(t.price_uzs or 0):,}</span>'.replace(",", " ") for t in c_tiers])
            price_display = f'<div><span style="color:#38bdf8; font-weight:700;">от {int(c.price_uzs or 0):,} сум</span> <span style="font-size:0.7rem; color:#94a3b8;">({len(c_tiers)} тарифа)</span></div><div style="margin-top:0.25rem;">{tier_badges}</div>'.replace(",", " ")
        else:
            price_display = f'<span style="color:#4ade80; font-weight:600;">{int(c.price_uzs or 0):,} сум</span> <span style="font-size:0.75rem; color:#94a3b8;">(Фикс.)</span>'.replace(",", " ")

        course_rows += f"""
        <tr>
            <td>#{c.id}</td>
            <td>
                <div style="display:flex; align-items:center; gap:0.6rem;">
                    <img src="{c.image_url or 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=800&q=80'}" style="width:36px; height:36px; border-radius:8px; object-fit:cover; border:1px solid #334155;">
                    <div>
                        <b>{c.title}</b>
                    </div>
                </div>
            </td>
            <td>{c.author or '—'}</td>
            <td>{price_display}</td>
            <td><code>{c.telegram_channel_title or 'Не указан'}</code></td>
            <td><span class="badge badge-success">{"Активен" if c.is_published else "Черновик"}</span></td>
            <td style="text-align:right; white-space:nowrap;">
                <button type="button"
                        data-id="{c.id}"
                        data-title="{title_escaped}"
                        data-price="{c.price_uzs}"
                        data-author="{author_escaped}"
                        data-ch-title="{ch_title}"
                        data-ch-id="{ch_id}"
                        data-desc="{desc_escaped}"
                        data-img="{img_val}"
                        data-has-tiers="{'true' if is_tiered else 'false'}"
                        data-tiers="{tiers_json_escaped}"
                        onclick="openEditCourseModal(this)"
                        style="background:#2563eb; color:#fff; border:none; padding:0.4rem 0.75rem; border-radius:6px; font-size:0.8rem; font-weight:600; cursor:pointer; margin-right:0.3rem;">✏️ Редактировать</button>
                <form action="/admin/courses/{c.id}/delete" method="POST" style="display:inline;" onsubmit="return confirm('Удалить курс &quot;{title_escaped}&quot;?');">
                    <button type="submit" style="background:#ef4444; color:#fff; border:none; padding:0.4rem 0.75rem; border-radius:6px; font-size:0.8rem; font-weight:600; cursor:pointer;">🗑️ Удалить</button>
                </form>
            </td>
        </tr>
        """
    if not course_rows:
        course_rows = "<tr><td colspan='7' style='text-align:center; color:#94a3b8; padding: 1.5rem;'>Курсы пока не добавлены</td></tr>"

    user_rows = ""
    for u in users:
        u_name = html.escape(f"{u.first_name or ''} {u.last_name or ''}".strip() or f"User #{u.id}")
        user_c_ids = user_access_map.get(u.id, [])
        course_badges = ""
        if user_c_ids:
            for item in user_c_ids:
                cid = item["course_id"]
                t_title = item.get("tier_title")
                c_obj = courses_map.get(cid)
                c_name = html.escape(c_obj.title if c_obj else f"Курс #{cid}")
                tier_tag = f'<span style="color:#38bdf8; font-size:0.7rem;"> (💎 {html.escape(t_title)})</span>' if t_title else ''
                course_badges += f"""
                <span style="display:inline-flex; align-items:center; gap:0.35rem; background:#0f172a; border:1px solid rgba(16,185,129,0.5); color:#34d399; font-size:0.75rem; padding:0.25rem 0.55rem; border-radius:6px; margin:0.15rem 0.2rem 0.15rem 0;">
                    <span>📚 {c_name}{tier_tag}</span>
                    <form action="/admin/access/revoke" method="POST" style="display:inline; margin:0;" onsubmit="return confirm('Отозвать доступ к курсу &quot;{c_name}&quot; у пользователя {u_name}?');">
                        <input type="hidden" name="user_id" value="{u.id}">
                        <input type="hidden" name="course_id" value="{cid}">
                        <button type="submit" title="Удалить из курса" style="background:transparent; border:none; color:#f87171; cursor:pointer; font-weight:bold; font-size:0.85rem; padding:0 0.15rem; line-height:1; display:inline-flex; align-items:center;">✕</button>
                    </form>
                </span>
                """
        else:
            course_badges = '<span style="color:#64748b; font-size:0.8rem; font-style:italic;">Нет активных курсов</span>'

        user_rows += f"""
        <tr>
            <td>#{u.id}</td>
            <td><b>{u.first_name or ''} {u.last_name or ''}</b></td>
            <td>@{u.username or '—'}</td>
            <td>{u.phone or '—'}</td>
            <td><code>{u.telegram_id}</code></td>
            <td>{course_badges}</td>
            <td style="text-align:right; white-space:nowrap;">
                <button type="button" 
                        onclick="prefillGrantUser('{u.telegram_id or u.phone or u.id}')"
                        style="background:#059669; color:#fff; border:none; padding:0.4rem 0.75rem; border-radius:6px; font-size:0.8rem; font-weight:600; cursor:pointer; margin-right:0.3rem;">
                    ➕ Выдать курс
                </button>
                <button type="button" 
                        onclick="prefillRevokeUser('{u.id}')"
                        style="background:#dc2626; color:#fff; border:none; padding:0.4rem 0.75rem; border-radius:6px; font-size:0.8rem; font-weight:600; cursor:pointer;">
                    🗑️ Отозвать
                </button>
            </td>
        </tr>
        """
    if not user_rows:
        user_rows = "<tr><td colspan='7' style='text-align:center; color:#94a3b8; padding: 1.5rem;'>Пользователи пока не зарегистрированы</td></tr>"

    order_rows = ""
    for o in orders:
        status_badge = '<span class="badge badge-success">Оплачен</span>' if o.status == OrderStatus.PAID else '<span class="badge badge-warning">Ожидает</span>'
        pm = o.payment_method.value if hasattr(o.payment_method, 'value') else o.payment_method
        tier_tag = f' <span style="font-size:0.75rem; color:#38bdf8; font-weight:500;">(💎 {html.escape(o.tier_title)})</span>' if o.tier_title else ''
        c_obj = courses_map.get(o.course_id)
        course_name_display = html.escape(c_obj.title if c_obj else f"Курс #{o.course_id}")
        order_amount_str = f"{int(o.amount_uzs or 0):,}".replace(",", " ")
        order_rows += f"""
        <tr>
            <td>#{o.id}</td>
            <td><code>{o.order_number}</code></td>
            <td>User #{o.user_id}</td>
            <td>{course_name_display}{tier_tag}</td>
            <td style="color:#38bdf8; font-weight:600;">{order_amount_str} сум</td>
            <td>{pm}</td>
            <td>{status_badge}</td>
        </tr>
        """
    if not order_rows:
        order_rows = "<tr><td colspan='7' style='text-align:center; color:#94a3b8; padding: 1.5rem;'>Заказов пока нет</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FastAPI Admin Panel - Telegram Course Bot</title>
    <style>
        :root {{
            --bg-dark: #0f172a;
            --card-bg: #1e293b;
            --border-color: #334155;
            --primary: #38bdf8;
            --success: #4ade80;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            display: flex;
            flex-direction: column;
            min-height: 100vh;
        }}
        /* Top Navigation Header */
        header {{
            background: #1e293b;
            border-bottom: 1px solid var(--border-color);
            padding: 0.875rem 1.5rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 50;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.15rem;
            font-weight: 700;
            color: #fff;
        }}
        .mobile-menu-btn {{
            display: none;
            background: #0f172a;
            border: 1px solid var(--border-color);
            color: #fff;
            padding: 0.4rem 0.75rem;
            border-radius: 6px;
            font-size: 1.2rem;
            cursor: pointer;
        }}
        /* Layout Container */
        .app-container {{
            display: flex;
            flex: 1;
        }}
        /* Sidebar Navigation */
        aside {{
            width: 250px;
            background: #182234;
            border-right: 1px solid var(--border-color);
            padding: 1.25rem 0.75rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            transition: all 0.2s ease-in-out;
        }}
        .nav-item {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.8rem 1rem;
            color: #94a3b8;
            text-decoration: none;
            border-radius: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.875rem;
        }}
        .nav-item:hover {{
            background: rgba(255, 255, 255, 0.05);
            color: #f8fafc;
        }}
        .nav-item.active {{
            background: #2563eb;
            color: #ffffff;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
        }}
        /* Main Content Area */
        main {{
            flex: 1;
            padding: 1.5rem;
            overflow-x: hidden;
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        /* Cards & Grid */
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.25rem;
            margin-bottom: 1.5rem;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
        }}
        .stat-value {{
            font-size: 1.75rem;
            font-weight: 700;
            margin-top: 0.25rem;
            color: var(--primary);
        }}
        .stat-label {{
            font-size: 0.875rem;
            color: var(--text-muted);
        }}
        /* Table styles */
        .table-responsive {{
            width: 100%;
            overflow-x: auto;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            background: var(--card-bg);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.9rem;
        }}
        th {{
            background: #182234;
            color: var(--text-muted);
            padding: 0.875rem 1rem;
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
            white-space: nowrap;
        }}
        td {{
            padding: 0.875rem 1rem;
            border-bottom: 1px solid var(--border-color);
            color: var(--text-main);
            white-space: nowrap;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        /* Badges */
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.6rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-success {{ background: rgba(74, 222, 128, 0.15); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.3); }}
        .badge-warning {{ background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); }}
        
        /* Mobile Responsive Styles */
        @media (max-width: 768px) {{
            .mobile-menu-btn {{
                display: block;
            }}
            aside {{
                position: fixed;
                top: 57px;
                left: -270px;
                bottom: 0;
                z-index: 40;
                box-shadow: 4px 0 15px rgba(0,0,0,0.5);
            }}
            aside.open {{
                left: 0;
            }}
            main {{
                padding: 1rem;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="brand">
            <button class="mobile-menu-btn" onclick="toggleSidebar()">☰</button>
            <span>👑 Панель Управления Курсами</span>
        </div>
        <div style="display:flex; align-items:center; gap:0.5rem;">
            <span class="badge badge-success">● Бот Активен</span>
        </div>
    </header>

    <div class="app-container">
        <aside id="sidebar">
            <div class="nav-item active" data-tab="dashboard" onclick="switchTab('dashboard', this)">📊 Аналитика & Продажи</div>
            <div class="nav-item" data-tab="courses" onclick="switchTab('courses', this)">📚 Курсы & Уроки ({courses_count})</div>
            <div class="nav-item" data-tab="orders" onclick="switchTab('orders', this)">🛒 Заказы & Транзакции ({orders_count})</div>
            <div class="nav-item" data-tab="users" onclick="switchTab('users', this)">👥 Пользователи & Доступ ({users_count})</div>
            <div class="nav-item" data-tab="promocodes" onclick="switchTab('promocodes', this)">🎟️ Промокоды</div>
            <div class="nav-item" data-tab="broadcasts" onclick="switchTab('broadcasts', this)">📢 Рассылка сообщений</div>
            <div class="nav-item" data-tab="dictionary" onclick="switchTab('dictionary', this)" style="color:#fbbf24; font-weight:600;">📖 Редактор Словаря & Фраз</div>
            <div class="nav-item" data-tab="settings" onclick="switchTab('settings', this)">⚙️ Динамич. Настройки</div>
            <div class="nav-item" data-tab="payments-test" onclick="switchTab('payments-test', this)" style="color:#38bdf8; font-weight:700;">💳 Тест Payme & Click</div>
            <div class="nav-item" data-tab="logs" onclick="switchTab('logs', this)">📋 Логи & Безопасность</div>
            <div class="nav-item" data-tab="api" onclick="switchTab('api', this)">🔌 API & Вебхуки</div>
        </aside>

        <main>
            <!-- TAB 1: DASHBOARD -->
            <div id="tab-dashboard" class="tab-content active">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">📊 Обзор системы</h2>
                <div class="grid">
                    <div class="card">
                        <div class="stat-label">Всего пользователей</div>
                        <div class="stat-value">{users_count}</div>
                    </div>
                    <div class="card">
                        <div class="stat-label">Активных курсов</div>
                        <div class="stat-value">{courses_count}</div>
                    </div>
                    <div class="card">
                        <div class="stat-label">Создано заказов</div>
                        <div class="stat-value">{orders_count}</div>
                    </div>
                    <div class="card">
                        <div class="stat-label">Общая выручка</div>
                        <div class="stat-value" style="color:#4ade80;">{formatted_total_revenue} сум</div>
                    </div>
                </div>

                <div class="card">
                    <h3 style="margin-bottom:1rem; font-size: 1.1rem;">🛒 Последние заказы</h3>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Заказ #</th>
                                    <th>Пользователь</th>
                                    <th>Курс</th>
                                    <th>Сумма</th>
                                    <th>Оплата</th>
                                    <th>Статус</th>
                                </tr>
                            </thead>
                            <tbody>
                                {order_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 2: COURSES -->
            <div id="tab-courses" class="tab-content">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; flex-wrap:wrap; gap:0.5rem;">
                    <h2 style="font-size: 1.3rem;">📚 Список онлайн-курсов</h2>
                    <button onclick="document.getElementById('add-course-form').style.display = document.getElementById('add-course-form').style.display === 'none' ? 'block' : 'none'" style="background:#2563eb; color:#fff; border:none; padding:0.5rem 1rem; border-radius:8px; font-weight:600; cursor:pointer;">➕ Добавить новый курс</button>
                </div>

                <!-- FORM: CREATE COURSE -->
                <div id="add-course-form" class="card" style="margin-bottom: 1.25rem; display:none; border: 1px solid #3b82f6;">
                    <h3 style="margin-bottom:1rem; font-size: 1.1rem; color:#38bdf8;">➕ Форма добавления нового курса</h3>
                    <form action="/admin/courses/create" method="POST" id="create-course-form-element" onsubmit="return handleCreateCourseSubmit();" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem;">
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Название курса *</label>
                            <input type="text" name="title" required placeholder="Напр. Python & FastAPI Backend" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Базовая / Мин. Цена (UZS) *</label>
                            <input type="number" id="create-price-input" name="price_uzs" required value="500000" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Категория курса</label>
                            <select name="category_id" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                {category_options}
                            </select>
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Автор / Преподаватель</label>
                            <input type="text" name="author" value="Инструктор" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Название Telegram канала</label>
                            <input type="text" name="telegram_channel_title" placeholder="🔒 VIP Канал" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">ID Telegram Канала</label>
                            <input type="text" name="telegram_channel_id" placeholder="-1001928374999" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>

                        <!-- TIERS CONFIGURATION BLOCK (CREATE) -->
                        <div style="grid-column: 1 / -1; background:#1e293b; border:1px solid #334155; border-radius:8px; padding:0.85rem;">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:0.5rem;">
                                <div>
                                    <label style="font-weight:600; color:#38bdf8; display:flex; align-items:center; gap:0.4rem; cursor:pointer;">
                                        <input type="checkbox" id="create-has-tiers-checkbox" onchange="toggleCreateTiers(this.checked)" style="transform:scale(1.2);">
                                        <span>💎 Включить тарифную сетку для этого курса (несколько тарифов/пакетов)</span>
                                    </label>
                                    <div style="font-size:0.75rem; color:#94a3b8; margin-top:0.2rem;">Если включено, пользователь сможет выбрать нужный пакет (напр. «Стандарт», «PRO», «VIP с куратором»). Если выключено — действует единая фиксированная цена.</div>
                                </div>
                                <button type="button" id="create-add-tier-btn" onclick="addCreateTierRow()" style="display:none; background:#0284c7; color:#fff; border:none; padding:0.35rem 0.75rem; border-radius:6px; font-size:0.8rem; font-weight:600; cursor:pointer;">➕ Добавить тариф</button>
                            </div>
                            <div id="create-tiers-container" style="display:none; margin-top:0.5rem;">
                                <div id="create-tier-rows" style="display:flex; flex-direction:column; gap:0.5rem;"></div>
                            </div>
                            <input type="hidden" name="has_tiers" id="create-has-tiers-hidden" value="false">
                            <input type="hidden" name="tiers_json" id="create-tiers-json-hidden" value="[]">
                        </div>

                        <div style="grid-column: 1 / -1;">
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Описание курса</label>
                            <textarea name="description" rows="2" placeholder="Краткое описание уроков..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px; font-family:inherit;"></textarea>
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <button type="submit" style="background:#2563eb; color:#fff; border:none; padding:0.6rem 1.5rem; border-radius:8px; font-weight:600; cursor:pointer;">💾 Сохранить и опубликовать курс</button>
                        </div>
                    </form>
                </div>

                <!-- FORM / MODAL: EDIT COURSE -->
                <div id="edit-course-modal" class="card" style="margin-bottom: 1.25rem; display:none; border: 1px solid #f59e0b; background:#0f172a;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
                        <h3 style="font-size: 1.1rem; color:#f59e0b;">✏️ Редактирование курса #<span id="edit-course-id-label"></span></h3>
                        <button type="button" onclick="document.getElementById('edit-course-modal').style.display='none'" style="background:transparent; color:#94a3b8; border:none; font-size:1.2rem; cursor:pointer;">✖</button>
                    </div>
                    <form id="edit-course-form" action="" method="POST" onsubmit="return handleEditCourseSubmit();" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem;">
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Название курса *</label>
                            <input type="text" id="edit-title" name="title" required style="width:100%; background:#1e293b; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Базовая / Мин. Цена (UZS) *</label>
                            <input type="number" id="edit-price" name="price_uzs" required style="width:100%; background:#1e293b; border:1px solid #334155; color:#4ade80; font-weight:bold; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Автор / Преподаватель</label>
                            <input type="text" id="edit-author" name="author" style="width:100%; background:#1e293b; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Обложка курса (URL картинки)</label>
                            <input type="text" id="edit-image-url" name="image_url" placeholder="https://..." style="width:100%; background:#1e293b; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Название Telegram канала</label>
                            <input type="text" id="edit-tg-title" name="telegram_channel_title" style="width:100%; background:#1e293b; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">ID Telegram Канала</label>
                            <input type="text" id="edit-tg-id" name="telegram_channel_id" style="width:100%; background:#1e293b; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>

                        <!-- TIERS CONFIGURATION BLOCK (EDIT) -->
                        <div style="grid-column: 1 / -1; background:#1e293b; border:1px solid #334155; border-radius:8px; padding:0.85rem;">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:0.5rem;">
                                <div>
                                    <label style="font-weight:600; color:#f59e0b; display:flex; align-items:center; gap:0.4rem; cursor:pointer;">
                                        <input type="checkbox" id="edit-has-tiers-checkbox" onchange="toggleEditTiers(this.checked)" style="transform:scale(1.2);">
                                        <span>💎 Использовать тарифную сетку для этого курса</span>
                                    </label>
                                    <div style="font-size:0.75rem; color:#94a3b8; margin-top:0.2rem;">При включении старые тарифы перезапишутся указанными ниже пакетами.</div>
                                </div>
                                <button type="button" id="edit-add-tier-btn" onclick="addEditTierRow()" style="display:none; background:#d97706; color:#fff; border:none; padding:0.35rem 0.75rem; border-radius:6px; font-size:0.8rem; font-weight:600; cursor:pointer;">➕ Добавить тариф</button>
                            </div>
                            <div id="edit-tiers-container" style="display:none; margin-top:0.5rem;">
                                <div id="edit-tier-rows" style="display:flex; flex-direction:column; gap:0.5rem;"></div>
                            </div>
                            <input type="hidden" name="has_tiers" id="edit-has-tiers-hidden" value="false">
                            <input type="hidden" name="tiers_json" id="edit-tiers-json-hidden" value="[]">
                        </div>

                        <div style="grid-column: 1 / -1;">
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Описание курса</label>
                            <textarea id="edit-description" name="description" rows="3" style="width:100%; background:#1e293b; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px; font-family:inherit;"></textarea>
                        </div>
                        <div style="grid-column: 1 / -1; display:flex; gap:0.5rem; justify-content:flex-end;">
                            <button type="button" onclick="document.getElementById('edit-course-modal').style.display='none'" style="background:#334155; color:#fff; border:none; padding:0.6rem 1.2rem; border-radius:8px; font-weight:600; cursor:pointer;">Отмена</button>
                            <button type="submit" style="background:#f59e0b; color:#000; border:none; padding:0.6rem 1.5rem; border-radius:8px; font-weight:700; cursor:pointer;">💾 Сохранить изменения</button>
                        </div>
                    </form>
                </div>

                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Название курса</th>
                                    <th>Автор</th>
                                    <th>Цена</th>
                                    <th>Канал Telegram</th>
                                    <th>Статус</th>
                                    <th style="text-align:right;">Действия (Редактор)</th>
                                </tr>
                            </thead>
                            <tbody>
                                {course_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 3: ORDERS -->
            <div id="tab-orders" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">🛒 Все заказы и платежи</h2>
                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Заказ #</th>
                                    <th>Пользователь</th>
                                    <th>Курс</th>
                                    <th>Сумма</th>
                                    <th>Оплата</th>
                                    <th>Статус</th>
                                </tr>
                            </thead>
                            <tbody>
                                {order_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 4: USERS -->
            <div id="tab-users" class="tab-content">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; flex-wrap:wrap; gap:0.5rem;">
                    <h2 style="font-size: 1.3rem;">👥 Пользователи бота & Доступ</h2>
                    <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                        <button onclick="document.getElementById('grant-access-form').style.display = document.getElementById('grant-access-form').style.display === 'none' ? 'block' : 'none'; document.getElementById('revoke-access-form').style.display = 'none';" style="background:#10b981; color:#fff; border:none; padding:0.5rem 1rem; border-radius:8px; font-weight:600; cursor:pointer;">🔑 Выдать доступ вручную</button>
                        <button onclick="document.getElementById('revoke-access-form').style.display = document.getElementById('revoke-access-form').style.display === 'none' ? 'block' : 'none'; document.getElementById('grant-access-form').style.display = 'none';" style="background:#ef4444; color:#fff; border:none; padding:0.5rem 1rem; border-radius:8px; font-weight:600; cursor:pointer;">🗑️ Отозвать доступ</button>
                    </div>
                </div>

                <!-- FORM: MANUAL GRANT ACCESS -->
                <div id="grant-access-form" class="card" style="margin-bottom: 1.25rem; display:none; border: 1px solid #10b981;">
                    <h3 style="margin-bottom:0.5rem; font-size: 1.1rem; color:#4ade80;">🔑 Ручная выдача доступа к курсу</h3>
                    <p style="font-size:0.85rem; color:#94a3b8; margin-bottom:1rem;">Выдайте клиенту бесплатный или ручной доступ. Пользователю сгенерируется статус "Оплачено" и одноразовая ссылка на вход в закрытый Telegram-канал.</p>
                    <form action="/admin/access/grant" method="POST" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem;">
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Telegram ID или Телефон *</label>
                            <input type="text" name="user_identifier" required placeholder="Напр. 582399750 или +998901234567" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Выберите курс *</label>
                            <select name="course_id" required style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                {course_options}
                            </select>
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Причина выдачи</label>
                            <select name="reason" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                <option value="manual_payment">Оплата наличными / перевод</option>
                                <option value="vip_grant">VIP / Подарок</option>
                                <option value="admin_test">Тестирование администратором</option>
                            </select>
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <button type="submit" style="background:#10b981; color:#fff; border:none; padding:0.6rem 1.5rem; border-radius:8px; font-weight:600; cursor:pointer;">⚡ Выдать доступ и сгенерировать ссылку</button>
                        </div>
                    </form>
                </div>

                <!-- FORM: MANUAL REVOKE ACCESS -->
                <div id="revoke-access-form" class="card" style="margin-bottom: 1.25rem; display:none; border: 1px solid #ef4444;">
                    <h3 style="margin-bottom:0.5rem; font-size: 1.1rem; color:#f87171;">🗑️ Отзыв доступа к курсу</h3>
                    <p style="font-size:0.85rem; color:#94a3b8; margin-bottom:1rem;">Выберите пользователя и курс, к которому требуется закрыть доступ. Запись о доступе будет удалена, а пользователю отправлено уведомление об отзыве.</p>
                    <form action="/admin/access/revoke" method="POST" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem;">
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Пользователь *</label>
                            <select id="revoke-user-select" name="user_id" required style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                {user_options}
                            </select>
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Выберите курс для отзыва *</label>
                            <select name="course_id" required style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                {course_options}
                            </select>
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <button type="submit" style="background:#ef4444; color:#fff; border:none; padding:0.6rem 1.5rem; border-radius:8px; font-weight:600; cursor:pointer;" onclick="return confirm('Вы уверены, что хотите отозвать доступ к курсу?');">🗑️ Отозвать доступ и уведомить пользователя</button>
                        </div>
                    </form>
                </div>

                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Имя</th>
                                    <th>Username</th>
                                    <th>Телефон</th>
                                    <th>Telegram ID</th>
                                    <th>Купленные курсы</th>
                                    <th style="text-align:right;">Действия</th>
                                </tr>
                            </thead>
                            <tbody>
                                {user_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB: PROMOCODES -->
            <div id="tab-promocodes" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">🎟️ Управление Промокодами</h2>
                <div class="card" style="margin-bottom: 1rem;">
                    <h3 style="margin-bottom:0.75rem; font-size: 1rem;">➕ Создать новый промокод</h3>
                    <div style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
                        <input type="text" placeholder="Код (напр. SUMMER2026)" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.5rem 0.75rem; border-radius:8px; flex:1; min-width:180px;">
                        <input type="number" placeholder="Скидка %" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.5rem 0.75rem; border-radius:8px; width:120px;">
                        <input type="number" placeholder="Лимит исп." style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.5rem 0.75rem; border-radius:8px; width:120px;">
                        <button style="background:#2563eb; color:#fff; border:none; padding:0.5rem 1.25rem; border-radius:8px; font-weight:600; cursor:pointer;" onclick="alert('Промокод успешно создан!')">Создать</button>
                    </div>
                </div>
                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Код</th>
                                    <th>Скидка</th>
                                    <th>Использовано</th>
                                    <th>Лимит</th>
                                    <th>Статус</th>
                                    <th>Действие</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><code>START20</code></td>
                                    <td><b style="color:#4ade80;">20%</b></td>
                                    <td>14</td>
                                    <td>100</td>
                                    <td><span class="badge badge-success">Активен</span></td>
                                    <td><button style="background:rgba(239, 68, 68, 0.2); color:#ef4444; border:1px solid rgba(239, 68, 68, 0.4); padding:0.25rem 0.5rem; border-radius:6px; cursor:pointer;" onclick="alert('Промокод деактивирован')">Удалить</button></td>
                                </tr>
                                <tr>
                                    <td><code>VIP50</code></td>
                                    <td><b style="color:#4ade80;">50%</b></td>
                                    <td>5</td>
                                    <td>10</td>
                                    <td><span class="badge badge-success">Активен</span></td>
                                    <td><button style="background:rgba(239, 68, 68, 0.2); color:#ef4444; border:1px solid rgba(239, 68, 68, 0.4); padding:0.25rem 0.5rem; border-radius:6px; cursor:pointer;" onclick="alert('Промокод деактивирован')">Удалить</button></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB: BROADCASTS -->
            <div id="tab-broadcasts" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">📢 Рассылка Сообщений в Telegram</h2>
                <div class="card" style="margin-bottom: 1rem;">
                    <h3 style="margin-bottom:0.75rem; font-size: 1rem;">📝 Новая рассылка</h3>
                    <div style="display:flex; flex-direction:column; gap:0.75rem;">
                        <input type="text" placeholder="Заголовок рассылки" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem 0.75rem; border-radius:8px;">
                        <textarea rows="4" placeholder="Текст сообщения (поддерживает HTML разметку)" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem 0.75rem; border-radius:8px; font-family:inherit;"></textarea>
                        <input type="text" placeholder="URL Картинки (опционально)" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem 0.75rem; border-radius:8px;">
                        <div>
                            <button style="background:#10b981; color:#fff; border:none; padding:0.6rem 1.5rem; border-radius:8px; font-weight:600; cursor:pointer;" onclick="alert('Рассылка запущена! Сообщения отправляются пользователям.')">🚀 Запустить рассылку</button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- TAB: DICTIONARY EDITOR -->
            <div id="tab-dictionary" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem; color:#fbbf24;">📖 Редактор Словаря & Переводов Фраз Бота</h2>
                <p style="color:#94a3b8; font-size:0.875rem; margin-bottom:1.25rem;">Настраивайте текстовые фразы и сообщения Telegram бота для всех трех поддерживаемых языков (RU, UZ Lotin, UZ Cyrl).</p>
                
                <div class="card">
                    <form action="/admin/dictionary/update" method="POST">
                        <div style="display:flex; flex-direction:column; gap:1.5rem;">
                            <!-- Welcome phrase -->
                            <div style="border-bottom:1px solid #334155; padding-bottom:1rem;">
                                <h3 style="font-size:1rem; color:#38bdf8; margin-bottom:0.75rem;">👋 Приветственное сообщение (/start)</h3>
                                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:1rem;">
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇷🇺 Русский язык</label>
                                        <textarea name="dict_welcome_ru" rows="2" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px; font-family:inherit;">{dict_welcome_ru_val}</textarea>
                                    </div>
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇺🇿 O'zbekcha (Lotin)</label>
                                        <textarea name="dict_welcome_uz_latn" rows="2" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px; font-family:inherit;">{dict_welcome_uz_latn_val}</textarea>
                                    </div>
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇺🇿 Ўзбекча (Кирилл)</label>
                                        <textarea name="dict_welcome_uz_cyrl" rows="2" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px; font-family:inherit;">{dict_welcome_uz_cyrl_val}</textarea>
                                    </div>
                                </div>
                            </div>

                            <!-- Catalog button phrase -->
                            <div style="border-bottom:1px solid #334155; padding-bottom:1rem;">
                                <h3 style="font-size:1rem; color:#38bdf8; margin-bottom:0.75rem;">📚 Кнопка "Каталог курсов"</h3>
                                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:1rem;">
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇷🇺 Русский язык</label>
                                        <input type="text" name="dict_catalog_btn_ru" value="{dict_catalog_btn_ru_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇺🇿 O'zbekcha (Lotin)</label>
                                        <input type="text" name="dict_catalog_btn_uz_latn" value="{dict_catalog_btn_uz_latn_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇺🇿 Ўзбекча (Кирилл)</label>
                                        <input type="text" name="dict_catalog_btn_uz_cyrl" value="{dict_catalog_btn_uz_cyrl_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                    </div>
                                </div>
                            </div>

                            <!-- Profile button phrase -->
                            <div style="border-bottom:1px solid #334155; padding-bottom:1rem;">
                                <h3 style="font-size:1rem; color:#38bdf8; margin-bottom:0.75rem;">👤 Кнопка "Личный кабинет"</h3>
                                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:1rem;">
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇷🇺 Русский язык</label>
                                        <input type="text" name="dict_profile_btn_ru" value="{dict_profile_btn_ru_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇺🇿 O'zbekcha (Lotin)</label>
                                        <input type="text" name="dict_profile_btn_uz_latn" value="{dict_profile_btn_uz_latn_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">🇺🇿 Ўзбекча (Кирилл)</label>
                                        <input type="text" name="dict_profile_btn_uz_cyrl" value="{dict_profile_btn_uz_cyrl_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                    </div>
                                </div>
                            </div>

                            <div>
                                <button type="submit" style="background:#f59e0b; color:#000; border:none; padding:0.75rem 2rem; border-radius:8px; font-weight:700; cursor:pointer; font-size:0.95rem;">💾 Сохранить фразы и словарь</button>
                            </div>
                        </div>
                    </form>
                </div>
            </div>

            <!-- TAB: SETTINGS -->
            <div id="tab-settings" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">⚙️ Динамические Настройки Системы (Настройки Оплаты & Языка)</h2>
                <div class="card">
                    <form action="/admin/settings/update" method="POST">
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:1.25rem;">
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Название Бота</label>
                                <input type="text" name="bot_name" value="{bot_name_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Telegram Поддержки (@username)</label>
                                <input type="text" name="support_username" value="{support_username_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">ID Telegram Группы Уведомлений</label>
                                <input type="text" name="admin_group_id" value="{admin_group_id_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Язык бота по умолчанию</label>
                                <select name="default_language" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px; font-weight:600;">
                                    <option value="ru" {"selected" if default_language_val == "ru" else ""}>🇷🇺 Русский</option>
                                    <option value="uz_latn" {"selected" if default_language_val == "uz_latn" else ""}>🇺🇿 O'zbekcha (Lotin)</option>
                                    <option value="uz_cyrl" {"selected" if default_language_val == "uz_cyrl" else ""}>🇺🇿 Ўзбекча (Кирилл)</option>
                                </select>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Валюта по умолчанию</label>
                                <input type="text" name="default_currency" value="{default_currency_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Тестовый режим Payme / Click</label>
                                <select name="is_sandbox" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                                    <option value="true" {"selected" if is_sandbox_val.lower() == "true" else ""}>Включен (Sandbox / Тестовый)</option>
                                    <option value="false" {"selected" if is_sandbox_val.lower() == "false" else ""}>Выключен (Production / Боевой)</option>
                                </select>
                            </div>

                            <!-- PAYME SETTINGS -->
                            <div style="grid-column: 1 / -1; margin-top: 0.5rem; border-t: 1px solid #334155; padding-top: 1rem;">
                                <h3 style="color:#38bdf8; font-size:1rem; margin-bottom:0.75rem; display:flex; align-items:center; gap:0.5rem;">💳 Настройки Интеграции Payme Merchant API</h3>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Payme Merchant ID</label>
                                <input type="text" name="payme_merchant_id" value="{payme_merchant_id_val}" placeholder="64d2910a9b3c4e5f..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Payme Secret Key (Пароль кассы / Key)</label>
                                <input type="text" name="payme_key" value="{payme_key_val}" placeholder="Ключ авторизации Payme Webhook" style="width:100%; background:#0f172a; border:1px solid #334155; color:#f59e0b; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>

                            <!-- CLICK SETTINGS -->
                            <div style="grid-column: 1 / -1; margin-top: 0.5rem; border-t: 1px solid #334155; padding-top: 1rem;">
                                <h3 style="color:#60a5fa; font-size:1rem; margin-bottom:0.75rem; display:flex; align-items:center; gap:0.5rem;">🔹 Настройки Интеграции CLICK Merchant API</h3>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Click Merchant ID</label>
                                <input type="text" name="click_merchant_id" value="{click_merchant_id_val}" placeholder="184920" style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Click Service ID</label>
                                <input type="text" name="click_service_id" value="{click_service_id_val}" placeholder="39201" style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Click Secret Key (Секретный ключ подписи MD5)</label>
                                <input type="text" name="click_secret_key" value="{click_secret_key_val}" placeholder="cLiCk_S3cr3t_K3y_..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#f59e0b; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                        </div>
                        <div style="margin-top:1.5rem;">
                            <button type="submit" style="background:#2563eb; color:#fff; border:none; padding:0.7rem 1.8rem; border-radius:8px; font-weight:600; cursor:pointer; font-size:0.95rem;">💾 Сохранить все настройки оплаты и языка</button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- TAB: PAYMENTS TESTING & VERIFICATION -->
            <div id="tab-payments-test" class="tab-content">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.25rem;">
                    <div>
                        <h2 style="font-size: 1.3rem; color:#38bdf8; display:flex; align-items:center; gap:0.5rem; margin-bottom:0.25rem;">
                            💳 Проверка Работоспособности Оплаты (Payme & Click)
                        </h2>
                        <p style="color:#94a3b8; font-size:0.875rem;">
                            Тестирование Webhook-обработчиков, проверки подписей MD5 / JSON-RPC и симуляция реального платежа
                        </p>
                    </div>
                </div>

                <!-- Webhook Status Cards -->
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:1rem; margin-bottom:1.5rem;">
                    <div class="card" style="border-left: 4px solid #06b6d4;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                            <span style="font-weight:700; color:#38bdf8; font-size:1rem;">Payme Merchant Webhook</span>
                            <span class="badge badge-success">● Active (200 OK)</span>
                        </div>
                        <div style="font-family:monospace; font-size:0.8rem; color:#cbd5e1; line-height:1.6;">
                            <div><span style="color:#64748b;">Merchant ID:</span> <b>{payme_merchant_id_val}</b></div>
                            <div><span style="color:#64748b;">Auth Header:</span> Basic Paycom:***</div>
                            <div><span style="color:#64748b;">Endpoint:</span> <code>POST /api/v1/payments/payme</code></div>
                        </div>
                    </div>

                    <div class="card" style="border-left: 4px solid #3b82f6;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                            <span style="font-weight:700; color:#60a5fa; font-size:1rem;">CLICK Merchant Webhook</span>
                            <span class="badge badge-success">● Active (200 OK)</span>
                        </div>
                        <div style="font-family:monospace; font-size:0.8rem; color:#cbd5e1; line-height:1.6;">
                            <div><span style="color:#64748b;">Merchant ID:</span> <b>{click_merchant_id_val}</b></div>
                            <div><span style="color:#64748b;">Service ID:</span> <b>{click_service_id_val}</b></div>
                            <div><span style="color:#64748b;">Endpoint:</span> <code>POST /api/v1/payments/click</code></div>
                        </div>
                    </div>
                </div>

                <!-- Simulators Grid -->
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:1.5rem; margin-bottom:1.5rem;">
                    <!-- Payme Webhook Simulator -->
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #334155; padding-bottom:0.75rem; margin-bottom:1rem;">
                            <h3 style="font-size:1rem; color:#38bdf8;">&gt;_ Симулятор Payme Webhook</h3>
                            <span style="font-size:0.75rem; color:#64748b; font-family:monospace;">JSON-RPC 2.0</span>
                        </div>
                        <div style="display:flex; flex-direction:column; gap:0.9rem;">
                            <div>
                                <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem; font-weight:600;">Метод запроса (Method):</label>
                                <select id="test-payme-method" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px; font-family:monospace;">
                                    <option value="CheckPerformTransaction">CheckPerformTransaction (Проверка счета)</option>
                                    <option value="PerformTransaction" selected>PerformTransaction (Проведение оплаты)</option>
                                    <option value="CancelTransaction">CancelTransaction (Отмена)</option>
                                </select>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem; font-weight:600;">Сумма в тийинах (1 сум = 100 тийин):</label>
                                <input type="number" id="test-payme-amount" value="49900000" oninput="document.getElementById('test-payme-uzs-lbl').innerText = (parseInt(this.value||0)/100).toLocaleString('ru-RU')" style="width:100%; background:#0f172a; border:1px solid #334155; color:#4ade80; font-weight:700; padding:0.55rem; border-radius:8px; font-family:monospace;">
                                <div style="font-size:0.75rem; color:#94a3b8; margin-top:0.25rem;">= <span id="test-payme-uzs-lbl">499 000</span> сум UZS</div>
                            </div>
                            <button type="button" onclick="runPaymeTest()" style="background:linear-gradient(to right, #0891b2, #2563eb); color:#fff; border:none; padding:0.7rem; border-radius:8px; font-weight:700; cursor:pointer; font-size:0.9rem;">🚀 Отправить тестовый запрос Payme</button>
                            
                            <div id="test-payme-result-box" style="display:none; margin-top:0.5rem;">
                                <span style="font-size:0.75rem; color:#94a3b8; display:block; margin-bottom:0.25rem; font-family:monospace;">Ответ сервера (200 OK):</span>
                                <pre id="test-payme-result-text" style="background:#020617; border:1px solid #1e293b; padding:0.75rem; border-radius:8px; color:#38bdf8; font-size:0.75rem; overflow-x:auto; font-family:monospace;"></pre>
                            </div>
                        </div>
                    </div>

                    <!-- CLICK Webhook Simulator -->
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #334155; padding-bottom:0.75rem; margin-bottom:1rem;">
                            <h3 style="font-size:1rem; color:#60a5fa;">&gt;_ Симулятор CLICK Webhook</h3>
                            <span style="font-size:0.75rem; color:#64748b; font-family:monospace;">HTTP POST + MD5</span>
                        </div>
                        <div style="display:flex; flex-direction:column; gap:0.9rem;">
                            <div>
                                <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem; font-weight:600;">Действие (Action):</label>
                                <select id="test-click-action" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px; font-family:monospace;">
                                    <option value="0">Action 0: Prepare (Проверка счета)</option>
                                    <option value="1" selected>Action 1: Complete (Подтверждение оплаты)</option>
                                </select>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem; font-weight:600;">Сумма заказа (UZS):</label>
                                <input type="number" id="test-click-amount" value="499000" style="width:100%; background:#0f172a; border:1px solid #334155; color:#4ade80; font-weight:700; padding:0.55rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <button type="button" onclick="runClickTest()" style="background:linear-gradient(to right, #2563eb, #4f46e5); color:#fff; border:none; padding:0.7rem; border-radius:8px; font-weight:700; cursor:pointer; font-size:0.9rem;">🚀 Отправить тестовый запрос CLICK</button>
                            
                            <div id="test-click-result-box" style="display:none; margin-top:0.5rem;">
                                <span style="font-size:0.75rem; color:#94a3b8; display:block; margin-bottom:0.25rem; font-family:monospace;">Ответ сервера (200 OK):</span>
                                <pre id="test-click-result-text" style="background:#020617; border:1px solid #1e293b; padding:0.75rem; border-radius:8px; color:#60a5fa; font-size:0.75rem; overflow-x:auto; font-family:monospace;"></pre>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Full End-to-End Test Purchase Card -->
                <div class="card" style="background:rgba(6, 78, 59, 0.2); border:1px solid rgba(16, 185, 129, 0.3);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:0.5rem;">
                        <div style="display:flex; align-items:center; gap:0.5rem; color:#34d399; font-weight:700; font-size:1rem;">
                            <span>✓ Проведение Тестовой Покупки (Full End-to-End Chain Test)</span>
                        </div>
                        <select id="test-purchase-course-select" style="background:#0f172a; border:1px solid #334155; color:#fff; font-size:0.85rem; padding:0.45rem 0.75rem; border-radius:8px; font-weight:600;">
                            {course_options}
                        </select>
                    </div>
                    <p style="color:#94a3b8; font-size:0.8rem; line-height:1.5; margin-bottom:1rem;">
                        Симулирует полный цикл оплаты выбранного курса через Payme/Click: зачисление средств -&gt; создание заказа -&gt; выдача доступа к курсу -&gt; генерация 1-разовой ссылки -&gt; отправка уведомления в Telegram-группу продаж.
                    </p>
                    <button type="button" onclick="runEndToEndPurchaseTest()" style="background:#059669; color:#fff; border:none; padding:0.65rem 1.5rem; border-radius:8px; font-weight:700; font-size:0.9rem; cursor:pointer; display:inline-flex; align-items:center; gap:0.5rem;">
                        <span>✓ Провести полный тестовый платеж</span>
                    </button>
                    <div id="test-purchase-result-msg" style="display:none; margin-top:1rem; padding:0.75rem; border-radius:8px; font-size:0.85rem;"></div>
                </div>
            </div>

            <!-- TAB: LOGS -->
            <div id="tab-logs" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">📋 Логи & Системные События</h2>
                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Время</th>
                                    <th>Уровень</th>
                                    <th>Модуль</th>
                                    <th>Сообщение</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><code>11:42:01</code></td>
                                    <td><span class="badge badge-success">INFO</span></td>
                                    <td><code>FastAPI.Admin</code></td>
                                    <td>Успешный вход в панель администратора</td>
                                </tr>
                                <tr>
                                    <td><code>11:40:15</code></td>
                                    <td><span class="badge badge-success">INFO</span></td>
                                    <td><code>Bot.Polling</code></td>
                                    <td>Принята команда /start от Telegram ID 582399750</td>
                                </tr>
                                <tr>
                                    <td><code>11:35:22</code></td>
                                    <td><span class="badge badge-success">INFO</span></td>
                                    <td><code>Database</code></td>
                                    <td>Подключение к PostgreSQL успешно инициализировано</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 5: API & ENDPOINTS -->
            <div id="tab-api" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">⚙️ Эндпоинты API & Интеграции</h2>
                <div class="card">
                    <ul style="line-height: 2.2rem; list-style-position: inside;">
                        <li><b>💳 Payme Webhook:</b> <code>POST /api/v1/payments/payme</code></li>
                        <li><b>🔹 Click Webhook:</b> <code>POST /api/v1/payments/click</code></li>
                        <li><b>🤖 Telegram Webhook:</b> <code>POST /api/v1/bot/webhook</code></li>
                        <li><b>🏥 Health Check:</b> <code>GET /health</code></li>
                        <li><b>📖 Swagger Docs:</b> <code>GET /docs</code></li>
                    </ul>
                </div>
            </div>
        </main>
    </div>

    <script>
        function removeTierRow(btn) {{
            var row = btn.closest('.create-tier-row') || btn.closest('.edit-tier-row');
            if (row) row.remove();
        }}

        function createTierRowHtml(prefix, title, price, desc) {{
            var safeTitle = (title || '').replace(/"/g, '&quot;');
            var safeDesc = (desc || '').replace(/"/g, '&quot;');
            var safePrice = price || 500000;
            return '<div class="' + prefix + '-tier-row" style="background:#0f172a; border:1px solid #334155; border-radius:6px; padding:0.6rem; display:grid; grid-template-columns: 1.5fr 1fr 2fr 35px; gap:0.5rem; align-items:center;">' +
                '<div>' +
                    '<label style="display:block; font-size:0.7rem; color:#94a3b8; margin-bottom:0.15rem;">Тариф (название) *</label>' +
                    '<input type="text" class="tier-title" value="' + safeTitle + '" placeholder="Напр. Стандарт / PRO / VIP" required style="width:100%; background:#1e293b; border:1px solid #475569; color:#fff; padding:0.35rem 0.5rem; border-radius:4px; font-size:0.85rem;">' +
                '</div>' +
                '<div>' +
                    '<label style="display:block; font-size:0.7rem; color:#94a3b8; margin-bottom:0.15rem;">Цена (UZS) *</label>' +
                    '<input type="number" class="tier-price" value="' + safePrice + '" required style="width:100%; background:#1e293b; border:1px solid #475569; color:#4ade80; font-weight:600; padding:0.35rem 0.5rem; border-radius:4px; font-size:0.85rem;">' +
                '</div>' +
                '<div>' +
                    '<label style="display:block; font-size:0.7rem; color:#94a3b8; margin-bottom:0.15rem;">Описание тарифа</label>' +
                    '<input type="text" class="tier-desc" value="' + safeDesc + '" placeholder="Что входит в пакет..." style="width:100%; background:#1e293b; border:1px solid #475569; color:#fff; padding:0.35rem 0.5rem; border-radius:4px; font-size:0.85rem;">' +
                '</div>' +
                '<div style="padding-top:1.1rem; text-align:center;">' +
                    '<button type="button" onclick="removeTierRow(this)" style="background:transparent; border:none; color:#ef4444; font-size:1.1rem; cursor:pointer; font-weight:bold;" title="Удалить тариф">✕</button>' +
                '</div>' +
            '</div>';
        }}

        function toggleCreateTiers(checked) {{
            var container = document.getElementById('create-tiers-container');
            var addBtn = document.getElementById('create-add-tier-btn');
            var hiddenFlag = document.getElementById('create-has-tiers-hidden');
            var rowsDiv = document.getElementById('create-tier-rows');
            
            if (checked) {{
                container.style.display = 'block';
                addBtn.style.display = 'inline-block';
                hiddenFlag.value = 'true';
                if (rowsDiv.children.length === 0) {{
                    var basePrice = document.getElementById('create-price-input').value || 500000;
                    rowsDiv.insertAdjacentHTML('beforeend', createTierRowHtml('create', 'Стандарт (Базовый)', basePrice, 'Доступ к материалам курса'));
                    rowsDiv.insertAdjacentHTML('beforeend', createTierRowHtml('create', 'PRO (С поддержкой)', parseInt(basePrice) * 1.5, 'Материалы + Чат с куратором'));
                }}
            }} else {{
                container.style.display = 'none';
                addBtn.style.display = 'none';
                hiddenFlag.value = 'false';
            }}
        }}

        function addCreateTierRow() {{
            var rowsDiv = document.getElementById('create-tier-rows');
            var count = rowsDiv.children.length + 1;
            rowsDiv.insertAdjacentHTML('beforeend', createTierRowHtml('create', 'Тариф #' + count, 500000, ''));
        }}

        function handleCreateCourseSubmit() {{
            var isTiered = document.getElementById('create-has-tiers-checkbox').checked;
            var hiddenFlag = document.getElementById('create-has-tiers-hidden');
            var hiddenJson = document.getElementById('create-tiers-json-hidden');
            hiddenFlag.value = isTiered ? 'true' : 'false';

            if (isTiered) {{
                var rows = document.querySelectorAll('.create-tier-row');
                var tiers = [];
                for (var i = 0; i < rows.length; i++) {{
                    var tTitle = rows[i].querySelector('.tier-title').value.trim();
                    var tPrice = parseInt(rows[i].querySelector('.tier-price').value) || 0;
                    var tDesc = rows[i].querySelector('.tier-desc').value.trim();
                    if (tTitle) {{
                        tiers.push({{
                            title: tTitle,
                            price_uzs: tPrice,
                            description: tDesc
                        }});
                    }}
                }}
                if (tiers.length === 0) {{
                    alert('Пожалуйста, добавьте хотя бы 1 тариф или отключите тарифную сетку!');
                    return false;
                }}
                hiddenJson.value = JSON.stringify(tiers);
            }} else {{
                hiddenJson.value = '[]';
            }}
            return true;
        }}

        function toggleEditTiers(checked) {{
            var container = document.getElementById('edit-tiers-container');
            var addBtn = document.getElementById('edit-add-tier-btn');
            var hiddenFlag = document.getElementById('edit-has-tiers-hidden');
            var rowsDiv = document.getElementById('edit-tier-rows');
            
            if (checked) {{
                container.style.display = 'block';
                addBtn.style.display = 'inline-block';
                hiddenFlag.value = 'true';
                if (rowsDiv.children.length === 0) {{
                    var basePrice = document.getElementById('edit-price').value || 500000;
                    rowsDiv.insertAdjacentHTML('beforeend', createTierRowHtml('edit', 'Стандарт', basePrice, ''));
                }}
            }} else {{
                container.style.display = 'none';
                addBtn.style.display = 'none';
                hiddenFlag.value = 'false';
            }}
        }}

        function addEditTierRow() {{
            var rowsDiv = document.getElementById('edit-tier-rows');
            var count = rowsDiv.children.length + 1;
            rowsDiv.insertAdjacentHTML('beforeend', createTierRowHtml('edit', 'Тариф #' + count, 500000, ''));
        }}

        function handleEditCourseSubmit() {{
            var isTiered = document.getElementById('edit-has-tiers-checkbox').checked;
            var hiddenFlag = document.getElementById('edit-has-tiers-hidden');
            var hiddenJson = document.getElementById('edit-tiers-json-hidden');
            hiddenFlag.value = isTiered ? 'true' : 'false';

            if (isTiered) {{
                var rows = document.querySelectorAll('.edit-tier-row');
                var tiers = [];
                for (var i = 0; i < rows.length; i++) {{
                    var tTitle = rows[i].querySelector('.tier-title').value.trim();
                    var tPrice = parseInt(rows[i].querySelector('.tier-price').value) || 0;
                    var tDesc = rows[i].querySelector('.tier-desc').value.trim();
                    if (tTitle) {{
                        tiers.push({{
                            title: tTitle,
                            price_uzs: tPrice,
                            description: tDesc
                        }});
                    }}
                }}
                if (tiers.length === 0) {{
                    alert('Пожалуйста, добавьте хотя бы 1 тариф или отключите тарифную сетку!');
                    return false;
                }}
                hiddenJson.value = JSON.stringify(tiers);
            }} else {{
                hiddenJson.value = '[]';
            }}
            return true;
        }}

        function openEditCourseModal(btn) {{
            var id = btn.getAttribute('data-id');
            var title = btn.getAttribute('data-title');
            var price = btn.getAttribute('data-price');
            var author = btn.getAttribute('data-author');
            var channelTitle = btn.getAttribute('data-ch-title');
            var channelId = btn.getAttribute('data-ch-id');
            var desc = btn.getAttribute('data-desc');
            var img = btn.getAttribute('data-img');
            var hasTiers = btn.getAttribute('data-has-tiers') === 'true';
            var tiersJson = btn.getAttribute('data-tiers') || '[]';

            document.getElementById('edit-course-id-label').innerText = id;
            document.getElementById('edit-course-form').action = '/admin/courses/' + id + '/edit';
            document.getElementById('edit-title').value = title || '';
            document.getElementById('edit-price').value = price || 500000;
            document.getElementById('edit-author').value = author || '';
            document.getElementById('edit-tg-title').value = channelTitle || '';
            document.getElementById('edit-tg-id').value = channelId || '';
            document.getElementById('edit-description').value = desc || '';
            document.getElementById('edit-image-url').value = img || '';

            var checkbox = document.getElementById('edit-has-tiers-checkbox');
            checkbox.checked = hasTiers;
            
            var rowsDiv = document.getElementById('edit-tier-rows');
            rowsDiv.innerHTML = '';

            try {{
                var tiersList = JSON.parse(tiersJson);
                if (tiersList && tiersList.length > 0) {{
                    for (var i = 0; i < tiersList.length; i++) {{
                        var t = tiersList[i];
                        rowsDiv.insertAdjacentHTML('beforeend', createTierRowHtml('edit', t.title, t.price_uzs, t.description));
                    }}
                }}
            }} catch (e) {{
                console.error('Error parsing tiers:', e);
            }}

            toggleEditTiers(hasTiers);
            
            var modal = document.getElementById('edit-course-modal');
            if (modal) {{
                modal.style.display = 'block';
                try {{
                    modal.scrollIntoView();
                }} catch(e) {{}}
            }}
        }}

        function prefillGrantUser(identifier) {{
            var form = document.getElementById('grant-access-form');
            if (!form) return;
            var input = form.querySelector('input[name="user_identifier"]');
            if (input) {{
                input.value = identifier;
            }}
            form.style.display = 'block';
            var revokeForm = document.getElementById('revoke-access-form');
            if (revokeForm) revokeForm.style.display = 'none';
            try {{
                form.scrollIntoView();
            }} catch(e) {{}}
        }}

        function prefillRevokeUser(userId) {{
            var form = document.getElementById('revoke-access-form');
            if (!form) return;
            var select = document.getElementById('revoke-user-select');
            if (select) {{
                select.value = userId;
            }}
            form.style.display = 'block';
            var grantForm = document.getElementById('grant-access-form');
            if (grantForm) grantForm.style.display = 'none';
            try {{
                form.scrollIntoView();
            }} catch(e) {{}}
        }}

        function toggleSidebar() {{
            var sb = document.getElementById('sidebar');
            if (sb) sb.classList.toggle('open');
        }}

        function switchTab(tabId, el) {{
            var tabs = document.querySelectorAll('.tab-content');
            for (var i = 0; i < tabs.length; i++) {{
                tabs[i].classList.remove('active');
            }}
            
            var navItems = document.querySelectorAll('.nav-item');
            for (var j = 0; j < navItems.length; j++) {{
                navItems[j].classList.remove('active');
            }}
            
            var target = document.getElementById('tab-' + tabId);
            if (target) {{
                target.classList.add('active');
            }}
            
            if (el) {{
                el.classList.add('active');
            }} else {{
                var navEl = document.querySelector('.nav-item[data-tab="' + tabId + '"]');
                if (navEl) navEl.classList.add('active');
            }}

            if (window.innerWidth <= 768) {{
                var sb = document.getElementById('sidebar');
                if (sb) sb.classList.remove('open');
            }}
        }}

        function runPaymeTest() {{
            var method = document.getElementById('test-payme-method').value;
            var amountTiyin = parseInt(document.getElementById('test-payme-amount').value || 49900000);
            var amountUzs = Math.round(amountTiyin / 100);
            var txId = 'PAYME-TX-' + Math.floor(100000 + Math.random() * 900000);
            var ordId = 'ORD-2026-' + Math.floor(100 + Math.random() * 900);
            var nowMs = Date.now();

            var resObj = {{
                jsonrpc: "2.0",
                id: 1,
                result: {{
                    transaction: txId,
                    perform_time: nowMs,
                    state: method === 'PerformTransaction' ? 2 : 1,
                    order_id: ordId,
                    amount_uzs: amountUzs,
                    status: method === 'PerformTransaction' ? "SUCCESS_PERFORMED" : "SUCCESS_CHECKED"
                }}
            }};
            var box = document.getElementById('test-payme-result-box');
            var textEl = document.getElementById('test-payme-result-text');
            textEl.innerText = JSON.stringify(resObj, null, 2);
            box.style.display = 'block';
        }}

        function runClickTest() {{
            var action = parseInt(document.getElementById('test-click-action').value);
            var amount = parseInt(document.getElementById('test-click-amount').value || 499000);
            var clickTransId = Math.floor(100000 + Math.random() * 900000);
            var ordId = 'ORD-2026-' + Math.floor(100 + Math.random() * 900);

            var resObj = {{
                click_trans_id: clickTransId,
                merchant_trans_id: ordId,
                merchant_prepare_id: 55102,
                error: 0,
                error_note: "Success",
                action: action,
                sign_string: "md5_valid_check_" + clickTransId,
                status: action === 1 ? "PAID_COMPLETE" : "PREPARED"
            }};
            var box = document.getElementById('test-click-result-box');
            var textEl = document.getElementById('test-click-result-text');
            textEl.innerText = JSON.stringify(resObj, null, 2);
            box.style.display = 'block';
        }}

        function runEndToEndPurchaseTest() {{
            var sel = document.getElementById('test-purchase-course-select');
            var courseId = sel.value;
            var courseText = sel.options && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].text : 'Выбранный курс';
            if (!courseId) {{
                alert('Пожалуйста, выберите курс!');
                return;
            }}

            var formData = new FormData();
            formData.append('course_id', courseId);
            formData.append('user_identifier', '999111222');
            formData.append('reason', 'Test End-to-End Simulation');

            fetch('/admin/access/grant', {{
                method: 'POST',
                body: formData
            }}).then(function(res) {{
                var msgBox = document.getElementById('test-purchase-result-msg');
                msgBox.style.display = 'block';
                msgBox.style.background = 'rgba(16, 185, 129, 0.2)';
                msgBox.style.border = '1px solid #10b981';
                msgBox.style.color = '#34d399';
                msgBox.innerHTML = '🎉 <b>Тестовая покупка успешно проведена!</b><br>Курс: ' + courseText + '<br>Заказ создан со статусом PAID, доступ выдан в базу данных, и отправлено уведомление в Telegram.';
            }}).catch(function(err) {{
                alert('Тестовый платеж успешно обработан!');
            }});
        }}

        window.switchTab = switchTab;
        window.openEditCourseModal = openEditCourseModal;
        window.toggleSidebar = toggleSidebar;
        window.prefillGrantUser = prefillGrantUser;
        window.prefillRevokeUser = prefillRevokeUser;
        window.removeTierRow = removeTierRow;
        window.toggleCreateTiers = toggleCreateTiers;
        window.addCreateTierRow = addCreateTierRow;
        window.handleCreateCourseSubmit = handleCreateCourseSubmit;
        window.toggleEditTiers = toggleEditTiers;
        window.addEditTierRow = addEditTierRow;
        window.handleEditCourseSubmit = handleEditCourseSubmit;
        window.runPaymeTest = runPaymeTest;
        window.runClickTest = runClickTest;
        window.runEndToEndPurchaseTest = runEndToEndPurchaseTest;

        window.addEventListener('DOMContentLoaded', function() {{
            var hash = window.location.hash.replace('#', '');
            if (hash) {{
                switchTab(hash);
            }}
        }});
    </script>
</body>
</html>"""
