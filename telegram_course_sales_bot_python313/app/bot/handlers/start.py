"""
aiogram 3 Start & Registration Handler
Supports referral link extraction (/start ref_123), user registration & dynamic main keyboard.
"""
import uuid
from typing import Optional
from aiogram import Router, F, types
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import User, SystemSetting
from app.services.i18n_service import get_active_dictionary, get_phrase, DEFAULT_TRANSLATIONS

router = Router(name="start")


async def get_main_keyboard(lang: str = "ru", db: Optional[AsyncSession] = None) -> ReplyKeyboardMarkup:
    try:
        if db:
            d = await get_active_dictionary(db)
        else:
            d = DEFAULT_TRANSLATIONS
    except Exception:
        d = DEFAULT_TRANSLATIONS

    lang_dict = d.get(lang, d.get("ru", DEFAULT_TRANSLATIONS["ru"]))
    catalog_txt = lang_dict.get("menuCatalog", "📚 Каталог курсов")
    mycourses_txt = lang_dict.get("menuMyCourses", "🎓 Мои курсы")
    profile_txt = lang_dict.get("menuProfile", "👤 Профиль и баланс")
    promocode_txt = lang_dict.get("enterPromoCode", "🎟️ Промокод")
    lang_txt = lang_dict.get("menuLanguage", "🌐 Сменить язык")
    support_txt = lang_dict.get("menuSupport", "💬 Поддержка & FAQ")

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=catalog_txt), KeyboardButton(text=mycourses_txt)],
            [KeyboardButton(text=profile_txt), KeyboardButton(text=promocode_txt)],
            [KeyboardButton(text=lang_txt), KeyboardButton(text=support_txt)]
        ],
        resize_keyboard=True
    )


async def is_profile_text(message: types.Message, db: AsyncSession) -> bool:
    txt = (message.text or "").strip()
    if txt in ["👤 Личный кабинет", "👤 Профиль и баланс", "👤 Profil va balans", "👤 Профиль ва баланс", "👤 Профиль", "/profile"]:
        return True
    try:
        d = await get_active_dictionary(db)
        for lang in ["ru", "uz_latn", "uz_cyrl"]:
            if txt == d.get(lang, {}).get("menuProfile"):
                return True
    except Exception:
        pass
    return False


async def is_promo_text(message: types.Message, db: AsyncSession) -> bool:
    txt = (message.text or "").strip()
    if txt in ["🎟️ Промокод", "🎟️ Promokod", "🎟️ Ввести промокод", "🎟️ Promokod kiritish", "🎟️ Промокод киритиш", "/promocode"]:
        return True
    try:
        d = await get_active_dictionary(db)
        for lang in ["ru", "uz_latn", "uz_cyrl"]:
            if txt == d.get(lang, {}).get("enterPromoCode"):
                return True
    except Exception:
        pass
    return False


async def is_language_text(message: types.Message, db: AsyncSession) -> bool:
    txt = (message.text or "").strip()
    if txt in ["🌐 Сменить язык", "🌐 Tilni o'zgartirish", "🌐 Тилни ўзгартириш", "/language"]:
        return True
    try:
        d = await get_active_dictionary(db)
        for lang in ["ru", "uz_latn", "uz_cyrl"]:
            if txt == d.get(lang, {}).get("menuLanguage"):
                return True
    except Exception:
        pass
    return False


async def is_support_text(message: types.Message, db: AsyncSession) -> bool:
    txt = (message.text or "").strip()
    if txt in [
        "💬 Поддержка & FAQ", "💬 Поддержка", "💬 Yordam & FAQ", "💬 Qo'llab-quvvatlash", 
        "💬 Qo'llab-quvvatlash & FAQ", "💬 Қўллаб-қувватлаш & FAQ", "💬 Қўллаб-қувватлаш", "💬 Ғордам & FAQ", "💬 Ёрдам & FAQ",
        "/support", "/faq"
    ]:
        return True
    try:
        d = await get_active_dictionary(db)
        for lang in ["ru", "uz_latn", "uz_cyrl"]:
            if txt == d.get(lang, {}).get("menuSupport"):
                return True
    except Exception:
        pass
    return False


@router.message(Command("language"))
@router.message(is_language_text)
async def cmd_language(message: types.Message, db: AsyncSession):
    telegram_id = message.from_user.id
    user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_res.scalar_one_or_none()
    lang = getattr(user, "language", "ru") if user else "ru"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [types.InlineKeyboardButton(text="🇺🇿 O'zbekcha (Lotin)", callback_data="lang_uz_latn")],
        [types.InlineKeyboardButton(text="🇺🇿 Ўзбекча (Кирилл)", callback_data="lang_uz_cyrl")]
    ])
    select_txt = await get_phrase("selectLanguage", lang, db=db)
    await message.answer(f"🌐 <b>{select_txt}</b>", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("lang_"))
async def set_language_callback(callback: types.CallbackQuery, db: AsyncSession):
    new_lang = callback.data.replace("lang_", "")
    telegram_id = callback.from_user.id
    
    stmt = select(User).where(User.telegram_id == telegram_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if user:
        if hasattr(user, "language"):
            user.language = new_lang
        else:
            setattr(user, "language", new_lang)
        await db.commit()
    
    txt = await get_phrase("languageSet", new_lang, db=db)
    main_kb = await get_main_keyboard(new_lang, db=db)
    await callback.message.answer(txt, reply_markup=main_kb)
    await callback.answer()


@router.callback_query(F.data == "act_lang")
async def act_lang_callback(callback: types.CallbackQuery, db: AsyncSession):
    telegram_id = callback.from_user.id
    user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_res.scalar_one_or_none()
    lang = getattr(user, "language", "ru") if user else "ru"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [types.InlineKeyboardButton(text="🇺🇿 O'zbekcha (Lotin)", callback_data="lang_uz_latn")],
        [types.InlineKeyboardButton(text="🇺🇿 Ўзбекча (Кирилл)", callback_data="lang_uz_cyrl")]
    ])
    select_txt = await get_phrase("selectLanguage", lang, db=db)
    await callback.message.answer(f"🌐 <b>{select_txt}</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(Command("profile"))
@router.message(is_profile_text)
async def cmd_profile(message: types.Message, db: AsyncSession):
    telegram_id = message.from_user.id
    stmt = select(User).where(User.telegram_id == telegram_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    
    user_lang = getattr(user, "language", "ru") if user else "ru"
    balance = getattr(user, "balance_uzs", 0) if user else 0
    ref_code = getattr(user, "referral_code", f"REF{telegram_id}") if user else f"REF{telegram_id}"
    
    profile_title = await get_phrase("profileTitle", user_lang, db=db)
    balance_label = await get_phrase("yourBalance", user_lang, db=db)
    ref_link_label = await get_phrase("yourRefLink", user_lang, db=db)
    promo_btn_txt = await get_phrase("enterPromoCode", user_lang, db=db)
    lang_btn_txt = await get_phrase("menuLanguage", user_lang, db=db)
    support_btn_txt = await get_phrase("menuSupport", user_lang, db=db)

    first_name = message.from_user.first_name or "Пользователь"
    txt = (
        f"👤 <b>{profile_title}</b>\n\n"
        f"👤 <b>Имя:</b> {first_name}\n"
        f"🆔 <b>Telegram ID:</b> <code>{telegram_id}</code>\n"
        f"💵 <b>{balance_label}</b> {balance:,} сум\n\n"
        f"🔗 <b>{ref_link_label}</b>\n"
        f"<code>https://t.me/EduStoreBot?start={ref_code}</code>"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=promo_btn_txt, callback_data="act_promo")],
        [types.InlineKeyboardButton(text=lang_btn_txt, callback_data="act_lang")],
        [types.InlineKeyboardButton(text=support_btn_txt, callback_data="act_support")]
    ])
        
    await message.answer(txt, reply_markup=kb, parse_mode="HTML")


@router.message(Command("promocode"))
@router.message(is_promo_text)
@router.callback_query(F.data == "act_promo")
async def cmd_promocode(event: types.Message | types.CallbackQuery, db: AsyncSession = None):
    msg = event.message if isinstance(event, types.CallbackQuery) else event
    txt = (
        "🎟️ <b>Активация промокода:</b>\n\n"
        "Отправьте секретный промокод в чат (например: <b>WELCOME20</b> или <b>BONUS100K</b>), "
        "чтобы получить скидку на курсы или бонусы на баланс!"
    )
    if isinstance(event, types.CallbackQuery):
        await msg.answer(txt, parse_mode="HTML")
        await event.answer()
    else:
        await msg.answer(txt, parse_mode="HTML")


@router.message(Command("support"))
@router.message(Command("faq"))
@router.message(is_support_text)
@router.callback_query(F.data == "act_support")
async def cmd_support(event: types.Message | types.CallbackQuery, db: AsyncSession = None):
    msg = event.message if isinstance(event, types.CallbackQuery) else event
    telegram_id = event.from_user.id
    user_lang = "ru"
    if db:
        user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        user_lang = getattr(user, "language", "ru") if user else "ru"

    support_title = await get_phrase("supportTitle", user_lang, db=db) if db else "💬 Служба поддержки и контакты:"
    support_welcome = await get_phrase("supportWelcome", user_lang, db=db) if db else "Добро пожаловать в центр помощи! Выберите нужный раздел:"
    operator_lbl = await get_phrase("supportOperator", user_lang, db=db) if db else "📞 Оператор:"
    phone_lbl = await get_phrase("supportPhone", user_lang, db=db) if db else "📞 Телефон:"
    
    faq_access_btn = await get_phrase("faqBtnHowToJoin", user_lang, db=db) if db else "❓ Как получить доступ к курсу?"
    faq_pay_btn = await get_phrase("faqBtnPaymentMethods", user_lang, db=db) if db else "💳 Способы оплаты (Payme / Click)"
    faq_promo_btn = await get_phrase("faqBtnPromoCode", user_lang, db=db) if db else "🎟️ Как применить промокод?"
    faq_ref_btn = await get_phrase("faqBtnReferral", user_lang, db=db) if db else "🎁 Реферальная программа"
    faq_op_btn = await get_phrase("faqBtnContactOperator", user_lang, db=db) if db else "💬 Написать оператору"

    # Dynamic Support Contacts from system_settings DB table
    support_username = "@edustore_support"
    support_link = "https://t.me/edustore_support"
    support_phone = "+998 71 200-00-00"
    if db:
        s_u = await db.execute(select(SystemSetting).where(SystemSetting.key == "support_username"))
        s_u_row = s_u.scalar_one_or_none()
        if s_u_row and s_u_row.value:
            support_username = s_u_row.value

        s_l = await db.execute(select(SystemSetting).where(SystemSetting.key == "support_link"))
        s_l_row = s_l.scalar_one_or_none()
        if s_l_row and s_l_row.value:
            support_link = s_l_row.value
        elif support_username:
            clean_u = support_username.lstrip("@")
            support_link = f"https://t.me/{clean_u}"

        s_p = await db.execute(select(SystemSetting).where(SystemSetting.key == "support_phone"))
        s_p_row = s_p.scalar_one_or_none()
        if s_p_row and s_p_row.value:
            support_phone = s_p_row.value

    txt = (
        f"💬 <b>{support_title}</b>\n\n"
        f"{support_welcome}\n\n"
        f"{operator_lbl} <b>{support_username}</b>\n"
        f"{phone_lbl} <b>{support_phone}</b>"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=faq_access_btn, callback_data="faq_access")],
        [types.InlineKeyboardButton(text=faq_pay_btn, callback_data="faq_pay")],
        [types.InlineKeyboardButton(text=faq_promo_btn, callback_data="faq_promo")],
        [types.InlineKeyboardButton(text=faq_ref_btn, callback_data="faq_ref")],
        [types.InlineKeyboardButton(text=f"{faq_op_btn} ({support_username})", url=support_link)]
    ])
    if isinstance(event, types.CallbackQuery):
        await msg.answer(txt, reply_markup=kb, parse_mode="HTML")
        await event.answer()
    else:
        await msg.answer(txt, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "faq_access")
async def faq_access_handler(callback: types.CallbackQuery, db: AsyncSession = None):
    telegram_id = callback.from_user.id
    user_lang = "ru"
    if db:
        user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        user_lang = getattr(user, "language", "ru") if user else "ru"

    ans = await get_phrase("faqAnswerHowToJoin", user_lang, db=db) if db else (
        "❓ <b>Как зайти в закрытый Telegram-канал курса?</b>\n\n"
        "Сразу после оплаты через Payme или Click бот сгенерирует персональную 1-разовую ссылку (<code>member_limit=1</code>). "
        "Ссылка придёт прямо в чат и аннулируется после первого перехода."
    )
    await callback.message.answer(ans, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "faq_pay")
async def faq_pay_handler(callback: types.CallbackQuery, db: AsyncSession = None):
    telegram_id = callback.from_user.id
    user_lang = "ru"
    if db:
        user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        user_lang = getattr(user, "language", "ru") if user else "ru"

    ans = await get_phrase("faqAnswerPaymentMethods", user_lang, db=db) if db else (
        "💳 <b>Способы оплаты:</b>\n\n"
        "Мы поддерживаем официальные платежные системы Узбекистана — Payme и CLICK. "
        "Все платежи зачисляются мгновенно с автоматической выдачей доступа к курсам."
    )
    await callback.message.answer(ans, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "faq_promo")
async def faq_promo_handler(callback: types.CallbackQuery, db: AsyncSession = None):
    telegram_id = callback.from_user.id
    user_lang = "ru"
    if db:
        user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        user_lang = getattr(user, "language", "ru") if user else "ru"

    ans = await get_phrase("faqAnswerPromoCode", user_lang, db=db) if db else (
        "🎟️ <b>Как активировать промокод?</b>\n\n"
        "Просто отправьте ваш промокод (например: <b>WELCOME20</b> или <b>BONUS100K</b>) текстовым сообщением в чат боту!"
    )
    await callback.message.answer(ans, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "faq_ref")
async def faq_ref_handler(callback: types.CallbackQuery, db: AsyncSession = None):
    telegram_id = callback.from_user.id
    user_lang = "ru"
    if db:
        user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        user_lang = getattr(user, "language", "ru") if user else "ru"

    ans = await get_phrase("faqAnswerReferral", user_lang, db=db) if db else (
        "🎁 <b>Реферальная система:</b>\n\n"
        "Скопируйте вашу уникальную ссылку в разделе <b>Профиль</b>. "
        "За каждый купленный курс вашим рефералом вы получаете 10% от стоимости на свой баланс!"
    )
    await callback.message.answer(ans, parse_mode="HTML")
    await callback.answer()


@router.message(F.text.startswith("WELCOME") | F.text.startswith("BONUS") | F.text.startswith("PROMO") | F.text.startswith("SKIDKA"))
async def process_promocode(message: types.Message, db: AsyncSession):
    code = message.text.strip().upper()
    if "BONUS" in code or "100K" in code:
        telegram_id = message.from_user.id
        stmt = select(User).where(User.telegram_id == telegram_id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if user:
            user.balance_uzs = getattr(user, "balance_uzs", 0) + 100000
            await db.commit()
            await message.answer(f"🎉 **Промокод '{code}' успешно применен!**\n\n💰 На ваш баланс начислено **100 000 сум**!", parse_mode="Markdown")
            return
    elif "WELCOME" in code or "PROMO" in code or "SKIDKA" in code:
        await message.answer(f"🎉 **Промокод '{code}' успешно применен!**\n\nСкидка **20%** применится автоматически при следующей покупке курса из каталога!", parse_mode="Markdown")
        return


@router.message(CommandStart())
@router.message(Command("start"))
@router.message(F.text.in_(["/start", "Главное меню", "🏠 Главное меню", "🏠 Asosiy menyu", "🏠 Асосий меню"]))
async def cmd_start(message: types.Message, db: AsyncSession, command: CommandObject = None):
    telegram_id = message.from_user.id
    ref_arg = command.args if command else None

    # Check if user exists
    stmt = select(User).where(User.telegram_id == telegram_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        ref_code = f"REF{message.from_user.id}"
        user = User(
            telegram_id=telegram_id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            referral_code=ref_code,
            referred_by=ref_arg if ref_arg else None,
            language="ru"
        )
        db.add(user)
        await db.commit()

    user_lang = getattr(user, "language", "ru") if user else "ru"
    welcome_phrase = await get_phrase("welcome", user_lang, db=db)
    user_first_name = message.from_user.first_name or "Пользователь"
    welcome_txt = f"👋 <b>Здравствуйте, {user_first_name}!</b>\n\n{welcome_phrase}"

    kb = await get_main_keyboard(user_lang, db=db)
    await message.answer(welcome_txt, reply_markup=kb, parse_mode="HTML")


@router.message(F.text)
async def handle_generic_text(message: types.Message, db: AsyncSession):
    text_query = message.text.strip()
    # Check if this is a search query for courses
    from app.database.models import Course
    stmt = select(Course).where(
        Course.is_published == True,
        (Course.title.ilike(f"%{text_query}%")) | (Course.description.ilike(f"%{text_query}%")) | (Course.author.ilike(f"%{text_query}%"))
    )
    res = await db.execute(stmt)
    found_courses = res.scalars().all()

    if found_courses:
        await message.answer(f"🔍 <b>Найдено курсов по запросу «{text_query}»:</b>", parse_mode="HTML")
        default_cover = "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=800&q=80"
        for c in found_courses:
            caption = (
                f"🎓 <b>{c.title}</b>\n\n"
                f"{c.description[:200]}...\n\n"
                f"👤 Автор: {c.author}\n"
                f"💵 Цена: <b>{c.price_uzs:,} сум</b>\n"
            )
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="💳 Купить через Payme", callback_data=f"buy_payme_{c.id}")],
                [types.InlineKeyboardButton(text="🔹 Купить через Click", callback_data=f"buy_click_{c.id}")],
                [types.InlineKeyboardButton(text="⬅️ В каталог", callback_data="back_categories")]
            ])
            img = c.image_url if (c.image_url and c.image_url.startswith("http")) else default_cover
            try:
                await message.answer_photo(photo=img, caption=caption, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await message.answer_photo(photo=default_cover, caption=caption, reply_markup=kb, parse_mode="HTML")
        return

    # If nothing matched, send main menu help
    telegram_id = message.from_user.id
    user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_res.scalar_one_or_none()
    user_lang = getattr(user, "language", "ru") if user else "ru"
    kb = await get_main_keyboard(user_lang, db=db)
    welcome_phrase = await get_phrase("welcome", user_lang, db=db)

    await message.answer(
        f"{welcome_phrase}",
        reply_markup=kb,
        parse_mode="HTML"
    )
