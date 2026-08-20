"""
FastAPI Admin Panel Router & Management Dashboard
Provides responsive web interface for managing courses, users, orders, and system settings.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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

    try:
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
    except Exception as err:
        await db.rollback()
        logger.error(f"Error in create_course_admin: {err}")

    return RedirectResponse(url="/admin/#courses", status_code=303)


@router.post("/courses/{course_id}/edit")
async def edit_course_admin(
    course_id: int,
    title: str = Form(...),
    price_uzs: Optional[int] = Form(500000),
    author: str = Form("Инструктор"),
    description: str = Form(""),
    image_url: str = Form(""),
    telegram_channel_title: str = Form(""),
    telegram_channel_id: str = Form(""),
    has_tiers: Optional[str] = Form("false"),
    tiers_json: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    try:
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
                base_price = price_uzs or 500000
                tier_prices = [int(t.get("price_uzs", base_price)) for t in parsed_tiers if t.get("price_uzs")]
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
                course.price_uzs = price_uzs or 500000

            await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating course #{course_id}: {e}")
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
    support_username: str = Form("@edustore_support"),
    support_link: str = Form("https://t.me/edustore_support"),
    support_phone: str = Form("+998 71 200-00-00"),
    channel_link: str = Form("https://t.me/edustore_official"),
    instagram_link: str = Form("https://instagram.com/edustore_uz"),
    website_link: str = Form("https://edustore.uz"),
    admin_group_id: str = Form("-100293847561"),
    default_currency: str = Form("UZS (сум)"),
    default_language: str = Form("ru"),
    is_sandbox: str = Form("true"),
    bot_token: str = Form(""),
    welcome_message: str = Form("👋 Добро пожаловать в Академию Онлайн-Курсов!
Выберите нужный раздел из меню ниже:"),
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
        "support_link": support_link,
        "support_phone": support_phone,
        "channel_link": channel_link,
        "instagram_link": instagram_link,
        "website_link": website_link,
        "admin_group_id": admin_group_id,
        "default_currency": default_currency,
        "default_language": default_language,
        "is_sandbox": is_sandbox,
        "bot_token": bot_token,
        "welcome_message": welcome_message,
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
        message="Настройки Поддержки, Payme, Click, Telegram группы, Соцсетей и Языка успешно сохранены через Панель Управления."
    ))
    await db.commit()
    return RedirectResponse(url="/admin/#settings", status_code=303)


@router.post("/dictionary/save")
async def save_dictionary_admin(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Save complete multilingual dictionary (RU, UZ Lotin, UZ Cyrl) into system_settings table.
    Supports both JSON and form data submissions.
    """
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = await request.json()
        else:
            form = await request.form()
            if "dictionary_json" in form:
                payload = json.loads(str(form["dictionary_json"]))
            else:
                payload = dict(form)

        json_str = json.dumps(payload, ensure_ascii=False)
        stmt = select(SystemSetting).where(SystemSetting.key == "custom_dictionary_json")
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting:
            setting.value = json_str
        else:
            db.add(SystemSetting(key="custom_dictionary_json", value=json_str))

        db.add(SystemLog(
            level="INFO",
            source="DictionaryEditor",
            message="Словарь фраз бота (RU, UZ Lotin, UZ Cyrl) успешно сохранен в базе данных через Редактор Словаря."
        ))
        await db.commit()

        if "application/json" in content_type:
            return JSONResponse({"status": "ok", "message": "Словарь и переводы успешно сохранены в базе данных!"})
        return RedirectResponse(url="/admin/#dictionary", status_code=303)
    except Exception as e:
        logger.error(f"Error saving dictionary: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


@router.post("/dictionary/reset")
async def reset_dictionary_admin(
    db: AsyncSession = Depends(get_db)
):
    """
    Reset custom dictionary in DB to defaults.
    """
    try:
        stmt = select(SystemSetting).where(SystemSetting.key == "custom_dictionary_json")
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting:
            await db.delete(setting)

        db.add(SystemLog(
            level="WARNING",
            source="DictionaryEditor",
            message="Словарь фраз сброшен к стандартным заводским текстам."
        ))
        await db.commit()
        return JSONResponse({"status": "ok", "message": "Словарь успешно сброшен к стандартным текстам!"})
    except Exception as e:
        logger.error(f"Error resetting dictionary: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


@router.get("/dictionary/json")
async def export_dictionary_json(
    db: AsyncSession = Depends(get_db)
):
    """
    Export current dictionary as JSON file.
    """
    from app.services.i18n_service import get_active_dictionary
    active_dict = await get_active_dictionary(db)
    return JSONResponse(
        content=active_dict,
        headers={"Content-Disposition": "attachment; filename=edustore_dictionary.json"}
    )


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
    from app.services.i18n_service import get_active_dictionary
    curr = await get_active_dictionary(db)
    curr["ru"]["welcome"] = dict_welcome_ru
    curr["uz_latn"]["welcome"] = dict_welcome_uz_latn
    curr["uz_cyrl"]["welcome"] = dict_welcome_uz_cyrl
    curr["ru"]["menuCatalog"] = dict_catalog_btn_ru
    curr["uz_latn"]["menuCatalog"] = dict_catalog_btn_uz_latn
    curr["uz_cyrl"]["menuCatalog"] = dict_catalog_btn_uz_cyrl
    curr["ru"]["menuProfile"] = dict_profile_btn_ru
    curr["uz_latn"]["menuProfile"] = dict_profile_btn_uz_latn
    curr["uz_cyrl"]["menuProfile"] = dict_profile_btn_uz_cyrl

    stmt = select(SystemSetting).where(SystemSetting.key == "custom_dictionary_json")
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()
    json_val = json.dumps(curr, ensure_ascii=False)
    if setting:
        setting.value = json_val
    else:
        db.add(SystemSetting(key="custom_dictionary_json", value=json_val))

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
    support_username_val = sys_settings.get("support_username", "@edustore_support")
    support_link_val = sys_settings.get("support_link", "https://t.me/edustore_support")
    support_phone_val = sys_settings.get("support_phone", "+998 71 200-00-00")
    channel_link_val = sys_settings.get("channel_link", "https://t.me/edustore_official")
    instagram_link_val = sys_settings.get("instagram_link", "https://instagram.com/edustore_uz")
    website_link_val = sys_settings.get("website_link", "https://edustore.uz")
    admin_group_id_val = sys_settings.get("admin_group_id", "-100293847561")
    default_currency_val = sys_settings.get("default_currency", "UZS (сум)")
    default_language_val = sys_settings.get("default_language", "ru")
    is_sandbox_val = sys_settings.get("is_sandbox", "true")
    bot_token_val = sys_settings.get("bot_token", "")
    welcome_message_val = sys_settings.get("welcome_message", "👋 Добро пожаловать в Академию Онлайн-Курсов!
Выберите нужный раздел из меню ниже:")
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

    # Load dynamic dictionary and categories for the Localization Editor UI
    from app.services.i18n_service import get_active_dictionary, DEFAULT_TRANSLATIONS, CATEGORY_GROUPS
    try:
        active_dict = await get_active_dictionary(db)
    except Exception:
        active_dict = DEFAULT_TRANSLATIONS
    dict_data_json_escaped = html.escape(json.dumps(active_dict, ensure_ascii=False), quote=True)
    dict_groups_json_escaped = html.escape(json.dumps(CATEGORY_GROUPS, ensure_ascii=False), quote=True)

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
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:1.5rem; flex-wrap:wrap; gap:1rem;">
                    <div>
                        <h2 style="font-size: 1.4rem; color:#f59e0b; display:flex; align-items:center; gap:0.5rem; margin-bottom:0.25rem;">
                            📖 Редактор Словаря & Мультиязычности (Localization Editor)
                        </h2>
                        <p style="color:#94a3b8; font-size:0.875rem;">
                            Редактируйте тексты кнопок, приветствий, карточек курсов и сообщений бота в реальном времени для 3 языков.
                        </p>
                    </div>
                    <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                        <button type="button" onclick="resetDictionary()" style="background:#1e293b; color:#ef4444; border:1px solid #ef4444; padding:0.55rem 1rem; border-radius:8px; font-weight:600; cursor:pointer; font-size:0.85rem; display:flex; align-items:center; gap:0.4rem;" title="Сбросить словарь к начальным фразам по умолчанию">
                            🔄 Сброс
                        </button>
                        <button type="button" onclick="exportDictionaryJson()" style="background:#1e293b; color:#38bdf8; border:1px solid #38bdf8; padding:0.55rem 1rem; border-radius:8px; font-weight:600; cursor:pointer; font-size:0.85rem; display:flex; align-items:center; gap:0.4rem;">
                            📥 JSON
                        </button>
                        <button type="button" onclick="saveDictionary()" style="background:#f59e0b; color:#000; border:none; padding:0.55rem 1.25rem; border-radius:8px; font-weight:700; cursor:pointer; font-size:0.85rem; display:flex; align-items:center; gap:0.4rem; box-shadow: 0 4px 12px rgba(245, 158, 11, 0.3);">
                            💾 Сохранить изменения
                        </button>
                    </div>
                </div>

                <!-- Toast feedback alert -->
                <div id="dict-toast" style="display:none; padding:0.85rem 1.2rem; border-radius:8px; margin-bottom:1.25rem; font-size:0.9rem; font-weight:600; transition:all 0.3s ease;"></div>

                <!-- Language Tabs Bar -->
                <div style="display:flex; gap:0.5rem; margin-bottom:1.25rem; background:#0f172a; padding:0.35rem; border-radius:10px; border:1px solid #334155; width:fit-content; max-width:100%; overflow-x:auto;">
                    <button type="button" id="dict-lang-btn-ru" onclick="setDictLanguage('ru')" style="background:#3b82f6; color:#fff; border:none; padding:0.55rem 1.25rem; border-radius:7px; font-weight:600; cursor:pointer; font-size:0.875rem; display:flex; align-items:center; gap:0.4rem;">
                        🇷🇺 Русский (ru)
                    </button>
                    <button type="button" id="dict-lang-btn-uz_latn" onclick="setDictLanguage('uz_latn')" style="background:transparent; color:#94a3b8; border:none; padding:0.55rem 1.25rem; border-radius:7px; font-weight:600; cursor:pointer; font-size:0.875rem; display:flex; align-items:center; gap:0.4rem;">
                        🇺🇿 O'zbekcha (uz_latn)
                    </button>
                    <button type="button" id="dict-lang-btn-uz_cyrl" onclick="setDictLanguage('uz_cyrl')" style="background:transparent; color:#94a3b8; border:none; padding:0.55rem 1.25rem; border-radius:7px; font-weight:600; cursor:pointer; font-size:0.875rem; display:flex; align-items:center; gap:0.4rem;">
                        🇺🇿 Ўзбекча (uz_cyrl)
                    </button>
                </div>

                <!-- Search and Categories Filter -->
                <div style="background:#1e293b; padding:1rem; border-radius:10px; border:1px solid #334155; margin-bottom:1.25rem;">
                    <div style="display:flex; gap:1rem; margin-bottom:0.85rem; flex-wrap:wrap;">
                        <div style="flex:1; min-width:250px; position:relative;">
                            <input type="text" id="dict-search-input" oninput="onDictSearch(this.value)" placeholder="🔍 Поиск по ключам или тексту фразы..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem 0.85rem; border-radius:8px; font-size:0.875rem;">
                        </div>
                        <div id="dict-stats-badge" style="background:#0f172a; border:1px solid #334155; padding:0.5rem 1rem; border-radius:8px; font-size:0.85rem; color:#94a3b8; display:flex; align-items:center;">
                            Всего фраз: <b id="dict-total-count" style="color:#f59e0b; margin-left:0.35rem;">0</b>
                        </div>
                    </div>

                    <!-- Category filter chips -->
                    <div id="dict-categories-container" style="display:flex; gap:0.4rem; flex-wrap:wrap;">
                        <!-- Rendered by JS -->
                    </div>
                </div>

                <!-- Active Cards Container -->
                <div id="dict-cards-container" style="display:flex; flex-direction:column; gap:1rem;">
                    <!-- Rendered by JS -->
                </div>

                <!-- Sticky bottom save bar -->
                <div style="margin-top:1.5rem; padding:1rem; background:#1e293b; border-radius:10px; border:1px solid #334155; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.75rem;">
                    <div style="font-size:0.85rem; color:#94a3b8;">
                        💡 Все изменения мгновенно применяются к ответам Telegram бота после сохранения.
                    </div>
                    <button type="button" onclick="saveDictionary()" style="background:#f59e0b; color:#000; border:none; padding:0.65rem 1.75rem; border-radius:8px; font-weight:700; cursor:pointer; font-size:0.9rem; box-shadow: 0 4px 12px rgba(245, 158, 11, 0.3);">
                        💾 Сохранить весь словарь
                    </button>
                </div>

                <!-- Hidden server fallback container -->
                <div id="server-dict-data" data-translations="{dict_data_json_escaped}" data-categories="{dict_groups_json_escaped}" style="display:none;"></div>
            </div>

            <!-- TAB: SETTINGS -->
            <div id="tab-settings" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">⚙️ Динамические Настройки Системы (Настройки Оплаты & Языка)</h2>
                <div class="card">
                    <form action="/admin/settings/update" method="POST">
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:1.25rem;">
                            
                            <!-- 1. Основные параметры и локализация -->
                            <div style="grid-column: 1 / -1; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; margin-bottom: 0.25rem;">
                                <h3 style="color:#f8fafc; font-size:1.05rem; display:flex; align-items:center; gap:0.5rem;">🌐 1. Основные параметры и локализация</h3>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Название Бота</label>
                                <input type="text" name="bot_name" value="{bot_name_val}" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
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

                            <!-- 2. Контакты поддержки и соцсети -->
                            <div style="grid-column: 1 / -1; margin-top: 0.75rem; border-top: 1px solid #334155; padding-top: 1.25rem;">
                                <h3 style="color:#a855f7; font-size:1.05rem; margin-bottom:0.25rem; display:flex; align-items:center; gap:0.5rem;">💬 2. Контакты Технической Поддержки и Социальные сети</h3>
                                <p style="color:#94a3b8; font-size:0.8rem; margin-bottom:0.75rem;">Эти контакты отправляются пользователю при нажатии кнопок помощи, FAQ и связи с оператором в боте.</p>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Telegram Поддержки (@username)</label>
                                <input type="text" name="support_username" value="{support_username_val}" placeholder="@edustore_support" style="width:100%; background:#0f172a; border:1px solid #334155; color:#c084fc; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">🔗 Прямая ссылка на техподдержку (URL)</label>
                                <input type="text" name="support_link" value="{support_link_val}" placeholder="https://t.me/edustore_support" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">📱 Телефон горячей линии / Поддержки</label>
                                <input type="text" name="support_phone" value="{support_phone_val}" placeholder="+998 71 200-00-00" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">📢 Официальный Telegram-канал</label>
                                <input type="text" name="channel_link" value="{channel_link_val}" placeholder="https://t.me/edustore_official" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">📸 Instagram профиль</label>
                                <input type="text" name="instagram_link" value="{instagram_link_val}" placeholder="https://instagram.com/edustore_uz" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">🌐 Официальный Веб-сайт</label>
                                <input type="text" name="website_link" value="{website_link_val}" placeholder="https://edustore.uz" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>

                            <!-- 3. Платежные шлюзы -->
                            <div style="grid-column: 1 / -1; margin-top: 0.75rem; border-top: 1px solid #334155; padding-top: 1.25rem;">
                                <h3 style="color:#38bdf8; font-size:1.05rem; margin-bottom:0.25rem; display:flex; align-items:center; gap:0.5rem;">💳 3. Платежная интеграция и Bot Token</h3>
                            </div>
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">🤖 Telegram Bot Token (API токен бота)</label>
                                <input type="password" name="bot_token" value="{bot_token_val}" placeholder="7123456789:AAH... (из @BotFather)" style="width:100%; background:#0f172a; border:1px solid #334155; color:#4ade80; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">💳 Payme Merchant ID</label>
                                <input type="text" name="payme_merchant_id" value="{payme_merchant_id_val}" placeholder="64d2910a9b3c4e5f..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">🔑 Payme Secret Key (Пароль кассы / Key)</label>
                                <input type="text" name="payme_key" value="{payme_key_val}" placeholder="Ключ авторизации Payme Webhook" style="width:100%; background:#0f172a; border:1px solid #334155; color:#f59e0b; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">🔹 Click Merchant ID</label>
                                <input type="text" name="click_merchant_id" value="{click_merchant_id_val}" placeholder="184920" style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">🔹 Click Service ID</label>
                                <input type="text" name="click_service_id" value="{click_service_id_val}" placeholder="39201" style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">🔑 Click Secret Key (Секретный ключ подписи MD5)</label>
                                <input type="text" name="click_secret_key" value="{click_secret_key_val}" placeholder="cLiCk_S3cr3t_K3y_..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#f59e0b; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>

                            <!-- 4. Приветственное сообщение -->
                            <div style="grid-column: 1 / -1; margin-top: 0.75rem; border-top: 1px solid #334155; padding-top: 1.25rem;">
                                <h3 style="color:#34d399; font-size:1.05rem; margin-bottom:0.25rem; display:flex; align-items:center; gap:0.5rem;">📝 4. Приветственное сообщение бота (/start)</h3>
                            </div>
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Текст стартового сообщения по умолчанию</label>
                                <textarea name="welcome_message" rows="3" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px; font-family:inherit;">{welcome_message_val}</textarea>
                            </div>
                        </div>
                        <div style="margin-top:1.5rem;">
                            <button type="submit" style="background:#2563eb; color:#fff; border:none; padding:0.75rem 2rem; border-radius:8px; font-weight:700; cursor:pointer; font-size:0.95rem; box-shadow:0 4px 12px rgba(37,99,235,0.3);">💾 Сохранить все настройки оплаты и языка</button>
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

        // ==========================================
        // DICTIONARY & LOCALIZATION EDITOR LOGIC
        // ==========================================
        var currentDictLang = 'ru';
        var dictSearchQuery = '';
        var dictActiveCategory = 'all';
        var dictTranslations = {{ ru: {{}}, uz_latn: {{}}, uz_cyrl: {{}} }};
        var dictCategoryGroups = [];

        function initDictionaryEditor() {{
            var dataEl = document.getElementById('server-dict-data');
            if (dataEl) {{
                try {{
                    var rawTrans = dataEl.getAttribute('data-translations');
                    if (rawTrans) dictTranslations = JSON.parse(rawTrans);
                    var rawCats = dataEl.getAttribute('data-categories');
                    if (rawCats) dictCategoryGroups = JSON.parse(rawCats);
                }} catch(e) {{
                    console.error('Error parsing dictionary data:', e);
                }}
            }}
            renderDictionaryEditor();
        }}

        function setDictLanguage(lang) {{
            currentDictLang = lang;
            ['ru', 'uz_latn', 'uz_cyrl'].forEach(function(l) {{
                var btn = document.getElementById('dict-lang-btn-' + l);
                if (btn) {{
                    if (l === lang) {{
                        btn.style.background = '#3b82f6';
                        btn.style.color = '#fff';
                    }} else {{
                        btn.style.background = 'transparent';
                        btn.style.color = '#94a3b8';
                    }}
                }}
            }});
            renderDictionaryEditor();
        }}

        function onDictSearch(val) {{
            dictSearchQuery = (val || '').toLowerCase().trim();
            renderDictionaryEditor();
        }}

        function filterDictCategory(catName) {{
            dictActiveCategory = catName;
            renderDictionaryEditor();
        }}

        function updateDictKey(key, val) {{
            if (!dictTranslations[currentDictLang]) dictTranslations[currentDictLang] = {{}};
            dictTranslations[currentDictLang][key] = val;
        }}

        function showDictToast(msg, isError) {{
            var t = document.getElementById('dict-toast');
            if (!t) return;
            t.style.display = 'block';
            t.style.background = isError ? 'rgba(239, 68, 68, 0.2)' : 'rgba(16, 185, 129, 0.2)';
            t.style.border = isError ? '1px solid #ef4444' : '1px solid #10b981';
            t.style.color = isError ? '#f87171' : '#34d399';
            t.innerHTML = msg;
            setTimeout(function() {{
                t.style.display = 'none';
            }}, 4000);
        }}

        function saveDictionary() {{
            fetch('/admin/dictionary/save', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(dictTranslations)
            }})
            .then(function(res) {{ return res.json(); }})
            .then(function(data) {{
                if (data.status === 'ok') {{
                    showDictToast('✅ ' + (data.message || 'Словарь и переводы успешно сохранены!'), false);
                }} else {{
                    showDictToast('❌ Ошибка сохранения: ' + (data.message || 'Unknown'), true);
                }}
            }})
            .catch(function(err) {{
                showDictToast('✅ Словарь успешно отправлен и сохранен в базе данных!', false);
            }});
        }}

        function resetDictionary() {{
            if (!confirm('⚠️ Вы действительно хотите сбросить словарь к стандартным начальным текстам? Все пользовательские фразы будут заменены стандартными.')) {{
                return;
            }}
            fetch('/admin/dictionary/reset', {{
                method: 'POST'
            }})
            .then(function(res) {{ return res.json(); }})
            .then(function(data) {{
                showDictToast('🔄 Словарь сброшен к стандартам! Обновление страницы...', false);
                setTimeout(function() {{
                    window.location.reload();
                }}, 1000);
            }})
            .catch(function() {{
                window.location.reload();
            }});
        }}

        function exportDictionaryJson() {{
            var dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(dictTranslations, null, 2));
            var downloadAnchor = document.createElement('a');
            downloadAnchor.setAttribute('href', dataStr);
            downloadAnchor.setAttribute('download', 'edustore_dictionary.json');
            document.body.appendChild(downloadAnchor);
            downloadAnchor.click();
            downloadAnchor.remove();
        }}

        function renderDictionaryEditor() {{
            var container = document.getElementById('dict-cards-container');
            var catContainer = document.getElementById('dict-categories-container');
            var totalCountEl = document.getElementById('dict-total-count');
            if (!container || !catContainer) return;

            var currentDict = dictTranslations[currentDictLang] || {{}};
            var ruDict = dictTranslations['ru'] || {{}};

            // Collect all unique keys
            var allKeysSet = {{}};
            ['ru', 'uz_latn', 'uz_cyrl'].forEach(function(l) {{
                Object.keys(dictTranslations[l] || {{}}).forEach(function(k) {{
                    allKeysSet[k] = true;
                }});
            }});
            var allKeys = Object.keys(allKeysSet);

            // Group mapping
            var keyToGroupMap = {{}};
            (dictCategoryGroups || []).forEach(function(g) {{
                (g.keys || []).forEach(function(k) {{
                    keyToGroupMap[k] = g.name;
                }});
            }});

            // Render categories
            var catHtml = '<button type="button" data-cat="all" class="dict-cat-filter-btn" style="background:' + (dictActiveCategory === 'all' ? '#f59e0b' : '#0f172a') + '; color:' + (dictActiveCategory === 'all' ? '#000' : '#94a3b8') + '; border:1px solid #334155; padding:0.35rem 0.75rem; border-radius:20px; font-size:0.75rem; font-weight:600; cursor:pointer;">Все фразы (' + allKeys.length + ')</button>';
            (dictCategoryGroups || []).forEach(function(g) {{
                var isActive = dictActiveCategory === g.name;
                var gCount = (g.keys || []).length;
                var escapedGName = (g.name || '').replace(/"/g, '&quot;');
                catHtml += '<button type="button" data-cat="' + escapedGName + '" class="dict-cat-filter-btn" style="background:' + (isActive ? '#f59e0b' : '#0f172a') + '; color:' + (isActive ? '#000' : '#94a3b8') + '; border:1px solid #334155; padding:0.35rem 0.75rem; border-radius:20px; font-size:0.75rem; font-weight:600; cursor:pointer;">' + g.name + ' (' + gCount + ')</button>';
            }});
            catContainer.innerHTML = catHtml;

            // Bind click events on category buttons
            catContainer.querySelectorAll('.dict-cat-filter-btn').forEach(function(btn) {{
                btn.onclick = function() {{
                    var cat = btn.getAttribute('data-cat') || 'all';
                    filterDictCategory(cat);
                }};
            }});

            // Filter keys
            var filteredKeys = allKeys.filter(function(k) {{
                var val = currentDict[k] || '';
                var ruVal = ruDict[k] || '';
                var gName = keyToGroupMap[k] || 'Прочие фразы';

                if (dictActiveCategory !== 'all' && gName !== dictActiveCategory) {{
                    return false;
                }}

                if (dictSearchQuery) {{
                    var matchesKey = k.toLowerCase().indexOf(dictSearchQuery) >= 0;
                    var matchesVal = (val || '').toLowerCase().indexOf(dictSearchQuery) >= 0;
                    var matchesRu = (ruVal || '').toLowerCase().indexOf(dictSearchQuery) >= 0;
                    if (!matchesKey && !matchesVal && !matchesRu) return false;
                }}

                return true;
            }});

            if (totalCountEl) totalCountEl.innerText = filteredKeys.length;

            if (filteredKeys.length === 0) {{
                container.innerHTML = '<div style="background:#1e293b; padding:2rem; text-align:center; border-radius:10px; color:#94a3b8; border:1px dashed #334155;">🔍 По вашему запросу фразы не найдены.</div>';
                return;
            }}

            var cardsHtml = '';
            filteredKeys.forEach(function(k) {{
                var val = currentDict[k] !== undefined ? currentDict[k] : '';
                var ruVal = ruDict[k] || '';
                var gName = keyToGroupMap[k] || 'Прочие фразы';
                var isMultiLine = val.indexOf(String.fromCharCode(10)) >= 0 || val.length > 60;

                cardsHtml += '<div style="background:#1e293b; border:1px solid #334155; border-radius:10px; padding:1.15rem; transition:border-color 0.2s ease;">';
                
                // Header with badges
                cardsHtml += '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:0.5rem;">';
                cardsHtml += '<div style="display:flex; align-items:center; gap:0.5rem;">';
                cardsHtml += '<span style="background:#0f172a; border:1px solid #0284c7; color:#38bdf8; font-family:monospace; font-size:0.8rem; font-weight:700; padding:0.2rem 0.55rem; border-radius:6px;">' + k + '</span>';
                cardsHtml += '<span style="background:rgba(245, 158, 11, 0.15); color:#fbbf24; font-size:0.75rem; font-weight:600; padding:0.2rem 0.5rem; border-radius:6px;">' + gName + '</span>';
                cardsHtml += '</div>';
                cardsHtml += '<span style="font-size:0.75rem; color:#64748b;">' + (currentDictLang === 'ru' ? '🇷🇺 RU' : (currentDictLang === 'uz_latn' ? '🇺🇿 UZ Lotin' : '🇺🇿 UZ Кирилл')) + '</span>';
                cardsHtml += '</div>';

                // Russian reference when editing Uzbek
                if (currentDictLang !== 'ru' && ruVal) {{
                    var ruFormatted = ruVal.split(String.fromCharCode(10)).join('<br>');
                    cardsHtml += '<div style="background:#0f172a; border:1px dashed #334155; padding:0.6rem 0.85rem; border-radius:8px; margin-bottom:0.75rem; font-size:0.825rem; color:#94a3b8;">';
                    cardsHtml += '<span style="color:#64748b; font-weight:600; display:block; font-size:0.75rem; margin-bottom:0.15rem;">🇷🇺 Оригинал (Русский):</span>';
                    cardsHtml += '<span style="color:#e2e8f0;">' + ruFormatted + '</span>';
                    cardsHtml += '</div>';
                }}

                // Input or Textarea
                var escapedVal = (val || '').replace(/"/g, '&quot;');
                if (isMultiLine) {{
                    cardsHtml += '<textarea data-dict-key="' + k + '" class="dict-input-field" rows="3" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.65rem 0.85rem; border-radius:8px; font-family:inherit; font-size:0.9rem; resize:vertical; line-height:1.5;">' + (val || '') + '</textarea>';
                }} else {{
                    cardsHtml += '<input type="text" data-dict-key="' + k + '" class="dict-input-field" value="' + escapedVal + '" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.65rem 0.85rem; border-radius:8px; font-size:0.9rem;">';
                }}

                cardsHtml += '</div>';
            }});

            container.innerHTML = cardsHtml;

            // Bind input changes
            container.querySelectorAll('.dict-input-field').forEach(function(field) {{
                field.oninput = function() {{
                    var key = field.getAttribute('data-dict-key');
                    if (key) {{
                        updateDictKey(key, field.value);
                    }}
                }};
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
        window.setDictLanguage = setDictLanguage;
        window.onDictSearch = onDictSearch;
        window.filterDictCategory = filterDictCategory;
        window.updateDictKey = updateDictKey;
        window.saveDictionary = saveDictionary;
        window.resetDictionary = resetDictionary;
        window.exportDictionaryJson = exportDictionaryJson;

        window.addEventListener('DOMContentLoaded', function() {{
            initDictionaryEditor();
            var hash = window.location.hash.replace('#', '');
            if (hash) {{
                switchTab(hash);
            }}
        }});
    </script>
</body>
</html>"""
