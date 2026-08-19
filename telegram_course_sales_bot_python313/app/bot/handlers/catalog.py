"""
aiogram 3 Catalog Handlers
Browse Categories, view Course cards, select Tiers, search courses, click Payme/Click checkout inline buttons.
"""
import uuid
import base64
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import Category, Course, CourseTier, Order, OrderStatus, PaymentMethod, UserCourseAccess, User, SystemSetting

router = Router(name="catalog")


@router.message(Command("catalog"))
@router.message(F.text.in_(["📚 Каталог курсов", "📚 Kurslar katalogi", "📚 Курслар каталоги"]))
async def show_categories(message: types.Message, db: AsyncSession):
    stmt = select(Category)
    res = await db.execute(stmt)
    categories = res.scalars().all()

    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}")])
    keyboard.append([InlineKeyboardButton(text="🔍 Поиск курса / Kurs izlash", callback_data="search_course")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("📁 <b>Категории онлайн-курсов / Kurslar kategoriyalari:</b>\nВыберите интересующую тему:", reply_markup=reply_markup, parse_mode="HTML")


@router.message(Command("mycourses"))
@router.message(F.text.in_(["🎓 Мои курсы", "🎓 Mening kurslarim", "🎓 Менинг курсларим"]))
async def show_my_courses(message: types.Message, db: AsyncSession):
    telegram_id = message.from_user.id
    user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_res.scalar_one_or_none()

    if not user:
        await message.answer("У вас пока нет купленных курсов. Откройте <b>📚 Каталог курсов</b> для выбора!", parse_mode="HTML")
        return

    stmt = (
        select(Course, UserCourseAccess)
        .join(UserCourseAccess, UserCourseAccess.course_id == Course.id)
        .where(UserCourseAccess.user_id == user.id)
    )
    res = await db.execute(stmt)
    rows = res.all()

    if not rows:
        await message.answer(
            "🎓 <b>У вас пока нет активных курсов.</b>\n\n"
            "Перейдите в <b>📚 Каталог курсов</b>, выберите подходящий курс и оплатите его через Payme или CLICK.",
            parse_mode="HTML"
        )
        return

    text = "🎓 <b>Ваши приобретенные курсы:</b>\n\n"
    keyboard = []
    for c, acc in rows:
        ch_title = c.telegram_channel_title or c.title
        tier_info = f" (💎 Тариф: {acc.tier_title})" if acc.tier_title else ""
        text += f"✅ <b>{c.title}</b>{tier_info}\n👤 Автор: {c.author}\n🔒 Канал: <code>{ch_title}</code>\n\n"
        if c.telegram_channel_id:
            keyboard.append([InlineKeyboardButton(text=f"↗️ Войти в {c.title[:20]}...", url="https://t.me/telegram")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None
    await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")


@router.callback_query(F.data == "back_categories")
async def back_to_categories_callback(callback: CallbackQuery, db: AsyncSession):
    stmt = select(Category)
    res = await db.execute(stmt)
    categories = res.scalars().all()

    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}")])
    keyboard.append([InlineKeyboardButton(text="🔍 Поиск курса / Kurs izlash", callback_data="search_course")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await callback.message.answer("📁 <b>Категории онлайн-курсов:</b>\nВыберите тему:", reply_markup=reply_markup, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "search_course")
async def search_course_callback(callback: CallbackQuery):
    await callback.message.answer("🔍 <b>Поиск курса:</b>\n\nНапишите название курса или ключевое слово в чат (например: <i>Python</i>, <i>SMM</i>, <i>Трейдинг</i>, <i>English</i>).", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("cat_"))
async def show_courses_by_category(callback: CallbackQuery, db: AsyncSession):
    cat_id = int(callback.data.split("_")[1])
    stmt = select(Course).where(Course.category_id == cat_id, Course.is_published == True)
    res = await db.execute(stmt)
    courses = res.scalars().all()

    if not courses:
        await callback.answer("В этой категории пока нет курсов", show_alert=True)
        return

    default_cover = "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=800&q=80"

    for c in courses:
        # Check if course has tiers
        t_stmt = select(CourseTier).where(CourseTier.course_id == c.id)
        t_res = await db.execute(t_stmt)
        tiers = t_res.scalars().all()

        kb_rows = []
        if c.has_tiers and tiers:
            tier_desc_lines = []
            for t in tiers:
                t_desc = f" ({t.description})" if t.description else ""
                tier_desc_lines.append(f"• 💎 <b>{t.title}</b>: {t.price_uzs:,} сум{t_desc}")
                kb_rows.append([InlineKeyboardButton(text=f"💎 Тариф «{t.title}» — {t.price_uzs:,} сум", callback_data=f"tier_{c.id}_{t.id}")])

            tiers_text = "\n".join(tier_desc_lines)
            caption = (
                f"🎓 <b>{c.title}</b>\n\n"
                f"{c.description[:200]}...\n\n"
                f"👤 Автор: {c.author}\n\n"
                f"📋 <b>Доступные тарифы:</b>\n{tiers_text}\n"
            )
        else:
            caption = (
                f"🎓 <b>{c.title}</b>\n\n"
                f"{c.description[:200]}...\n\n"
                f"👤 Автор: {c.author}\n"
                f"💵 Цена: <b>{c.price_uzs:,} сум</b>\n"
            )
            kb_rows.append([InlineKeyboardButton(text="💳 Купить через Payme", callback_data=f"buy_payme_{c.id}")])
            kb_rows.append([InlineKeyboardButton(text="🔹 Купить через Click", callback_data=f"buy_click_{c.id}")])

        kb_rows.append([InlineKeyboardButton(text="⬅️ Назад в категории", callback_data="back_categories")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        img = c.image_url if (c.image_url and c.image_url.startswith("http")) else default_cover
        try:
            await callback.message.answer_photo(photo=img, caption=caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.answer_photo(photo=default_cover, caption=caption, reply_markup=kb, parse_mode="HTML")

    await callback.answer()


@router.callback_query(F.data.startswith("tier_"))
async def choose_tier_callback(callback: CallbackQuery, db: AsyncSession):
    parts = callback.data.split("_")
    course_id = int(parts[1])
    tier_id = int(parts[2])

    c_res = await db.execute(select(Course).where(Course.id == course_id))
    course = c_res.scalar_one_or_none()

    t_res = await db.execute(select(CourseTier).where(CourseTier.id == tier_id))
    tier = t_res.scalar_one_or_none()

    if not course or not tier:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить через Payme", callback_data=f"buy_payme_{course.id}_{tier.id}")],
        [InlineKeyboardButton(text="🔹 Оплатить через Click", callback_data=f"buy_click_{course.id}_{tier.id}")],
        [InlineKeyboardButton(text="⬅️ Назад к выбору курса", callback_data=f"cat_{course.category_id or 1}")]
    ])

    await callback.message.answer(
        f"💎 <b>Выбран тариф: «{tier.title}»</b>\n\n"
        f"📚 Курс: <b>{course.title}</b>\n"
        f"💵 Стоимость: <b>{tier.price_uzs:,} сум</b>\n"
        f"📝 Описание тарифа: {tier.description or 'Полный доступ ко всем материалам тарифа'}\n\n"
        f"Выберите удобную платежную систему для оплаты:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_payme_"))
async def buy_payme_callback(callback: CallbackQuery, db: AsyncSession):
    parts = callback.data.split("_")
    course_id = int(parts[2])
    tier_id = int(parts[3]) if len(parts) > 3 else None

    course_res = await db.execute(select(Course).where(Course.id == course_id))
    course = course_res.scalar_one_or_none()
    if not course:
        await callback.answer("Курс не найден", show_alert=True)
        return

    tier_title = None
    amount_uzs = course.price_uzs
    if tier_id:
        t_res = await db.execute(select(CourseTier).where(CourseTier.id == tier_id))
        tier = t_res.scalar_one_or_none()
        if tier:
            amount_uzs = tier.price_uzs
            tier_title = tier.title

    telegram_id = callback.from_user.id
    user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_res.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id, first_name=callback.from_user.first_name, referral_code=f"REF{telegram_id}")
        db.add(user)
        await db.flush()

    order_num = f"PAYME-{uuid.uuid4().hex[:8].upper()}"
    new_order = Order(
        order_number=order_num,
        user_id=user.id,
        course_id=course.id,
        tier_id=tier_id,
        tier_title=tier_title,
        amount_uzs=amount_uzs,
        payment_method=PaymentMethod.PAYME,
        status=OrderStatus.PENDING
    )
    db.add(new_order)
    await db.commit()

    # Retrieve Payme Merchant ID
    m_res = await db.execute(select(SystemSetting).where(SystemSetting.key == "payme_merchant_id"))
    m_setting = m_res.scalar_one_or_none()
    merchant_id = m_setting.value if m_setting else "64d2910a9b3c4e5f6a7b8c9d"

    amount_tiyin = amount_uzs * 100
    param_str = f"m={merchant_id};ac.order_id={order_num};a={amount_tiyin}"
    b64_param = base64.b64encode(param_str.encode()).decode()
    pay_url = f"https://checkout.paycom.uz/{b64_param}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить в приложении Payme", url=pay_url)],
        [InlineKeyboardButton(text="⬅️ Назад в каталог", callback_data="back_categories")]
    ])

    tier_label = f" (Тариф: <b>{tier_title}</b>)" if tier_title else ""
    await callback.message.answer(
        f"🧾 <b>Счет на оплату курса через Payme:</b>\n\n"
        f"📚 Курс: <b>{course.title}</b>{tier_label}\n"
        f"💵 К оплате: <b>{amount_uzs:,} сум</b>\n"
        f"🔢 Номер заказа: <code>{order_num}</code>\n\n"
        f"Нажмите кнопку ниже для безопасной оплаты. Ссылка на закрытый канал курса будет выдана сразу после подтверждения транзакции.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_click_"))
async def buy_click_callback(callback: CallbackQuery, db: AsyncSession):
    parts = callback.data.split("_")
    course_id = int(parts[2])
    tier_id = int(parts[3]) if len(parts) > 3 else None

    course_res = await db.execute(select(Course).where(Course.id == course_id))
    course = course_res.scalar_one_or_none()
    if not course:
        await callback.answer("Курс не найден", show_alert=True)
        return

    tier_title = None
    amount_uzs = course.price_uzs
    if tier_id:
        t_res = await db.execute(select(CourseTier).where(CourseTier.id == tier_id))
        tier = t_res.scalar_one_or_none()
        if tier:
            amount_uzs = tier.price_uzs
            tier_title = tier.title

    telegram_id = callback.from_user.id
    user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_res.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id, first_name=callback.from_user.first_name, referral_code=f"REF{telegram_id}")
        db.add(user)
        await db.flush()

    order_num = f"CLICK-{uuid.uuid4().hex[:8].upper()}"
    new_order = Order(
        order_number=order_num,
        user_id=user.id,
        course_id=course.id,
        tier_id=tier_id,
        tier_title=tier_title,
        amount_uzs=amount_uzs,
        payment_method=PaymentMethod.CLICK,
        status=OrderStatus.PENDING
    )
    db.add(new_order)
    await db.commit()

    s_res = await db.execute(select(SystemSetting).where(SystemSetting.key == "click_service_id"))
    m_res = await db.execute(select(SystemSetting).where(SystemSetting.key == "click_merchant_id"))
    s_setting = s_res.scalar_one_or_none()
    m_setting = m_res.scalar_one_or_none()
    service_id = s_setting.value if s_setting else "39201"
    merchant_id = m_setting.value if m_setting else "184920"

    click_url = f"https://my.click.uz/services/pay?service_id={service_id}&merchant_id={merchant_id}&amount={amount_uzs}&transaction_param={order_num}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Оплатить через CLICK", url=click_url)],
        [InlineKeyboardButton(text="⬅️ Назад в каталог", callback_data="back_categories")]
    ])

    tier_label = f" (Тариф: <b>{tier_title}</b>)" if tier_title else ""
    await callback.message.answer(
        f"🧾 <b>Счет на оплату курса через CLICK:</b>\n\n"
        f"📚 Курс: <b>{course.title}</b>{tier_label}\n"
        f"💵 К оплате: <b>{amount_uzs:,} сум</b>\n"
        f"🔢 Номер заказа: <code>{order_num}</code>\n\n"
        f"Нажмите кнопку ниже для безопасной оплаты. Ссылка на закрытый канал курса будет выдана сразу после подтверждения транзакции.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()
