"""
aiogram 3 Start & Registration Handler
Supports referral link extraction (/start ref_123), user registration & main keyboard.
"""
import uuid
from aiogram import Router, F, types
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import User

router = Router(name="start")


def get_main_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    if lang == "uz_latn":
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 Kurslar katalogi"), KeyboardButton(text="🎓 Mening kurslarim")],
                [KeyboardButton(text="👤 Profil va balans"), KeyboardButton(text="🎟️ Promokod")],
                [KeyboardButton(text="🌐 Tilni o'zgartirish"), KeyboardButton(text="💬 Yordam & FAQ")]
            ],
            resize_keyboard=True
        )
    elif lang == "uz_cyrl":
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 Курслар каталоги"), KeyboardButton(text="🎓 Менинг курсларим")],
                [KeyboardButton(text="👤 Профиль ва баланс"), KeyboardButton(text="🎟️ Промокод")],
                [KeyboardButton(text="🌐 Тилни ўзгартириш"), KeyboardButton(text="💬 Ғордам & FAQ")]
            ],
            resize_keyboard=True
        )
    else:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 Каталог курсов"), KeyboardButton(text="🎓 Мои курсы")],
                [KeyboardButton(text="👤 Личный кабинет"), KeyboardButton(text="🎟️ Промокод")],
                [KeyboardButton(text="🌐 Сменить язык"), KeyboardButton(text="💬 Поддержка & FAQ")]
            ],
            resize_keyboard=True
        )


@router.message(Command("language"))
@router.message(F.text.in_(["🌐 Сменить язык", "🌐 Tilni o'zgartirish", "🌐 Тилни ўзгартириш"]))
async def cmd_language(message: types.Message):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [types.InlineKeyboardButton(text="🇺🇿 O'zbekcha (Lotin)", callback_data="lang_uz_latn")],
        [types.InlineKeyboardButton(text="🇺🇿 Ўзбекча (Кирилл)", callback_data="lang_uz_cyrl")]
    ])
    await message.answer("🌐 **Пожалуйста, выберите ваш язык / Iltimos, tilni tanlang:**", reply_markup=kb, parse_mode="Markdown")


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
    
    if new_lang == "uz_latn":
        txt = "✅ Til muvaffaqiyatli O'zbek tiliga (Lotin) o'zgartirildi! 🇺🇿"
    elif new_lang == "uz_cyrl":
        txt = "✅ Тил муваффақиятли Ўзбек тилига (Кирилл) ўзгартирилди! 🇺🇿"
    else:
        txt = "✅ Язык успешно изменен на Русский! 🇷🇺"
        
    await callback.message.answer(txt, reply_markup=get_main_keyboard(new_lang))
    await callback.answer()


@router.callback_query(F.data == "act_lang")
async def act_lang_callback(callback: types.CallbackQuery):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [types.InlineKeyboardButton(text="🇺🇿 O'zbekcha (Lotin)", callback_data="lang_uz_latn")],
        [types.InlineKeyboardButton(text="🇺🇿 Ўзбекча (Кирилл)", callback_data="lang_uz_cyrl")]
    ])
    await callback.message.answer("🌐 **Пожалуйста, выберите ваш язык / Iltimos, tilni tanlang:**", reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.message(Command("profile"))
@router.message(F.text.in_(["👤 Личный кабинет", "👤 Profil va balans", "👤 Профиль ва баланс", "👤 Профиль"]))
async def cmd_profile(message: types.Message, db: AsyncSession):
    telegram_id = message.from_user.id
    stmt = select(User).where(User.telegram_id == telegram_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    
    user_lang = getattr(user, "language", "ru") if user else "ru"
    balance = getattr(user, "balance_uzs", 0) if user else 0
    ref_code = getattr(user, "referral_code", f"REF{telegram_id}") if user else f"REF{telegram_id}"
    
    if user_lang == "uz_latn":
        txt = (
            f"👤 **Sizning profilingiz:**

"
            f"👤 **Ism:** {message.from_user.first_name}
"
            f"🆔 **Telegram ID:** `{telegram_id}`
"
            f"💵 **Balans:** {balance:,} so'm

"
            f"🔗 **Taklif havolangiz:**
"
            f"`https://t.me/EduStoreBot?start={ref_code}`"
        )
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🎟️ Promokod kiritish", callback_data="act_promo")],
            [types.InlineKeyboardButton(text="🌐 Tilni o'zgartirish", callback_data="act_lang")],
            [types.InlineKeyboardButton(text="💬 Qo'llab-quvvatlash", callback_data="act_support")]
        ])
    elif user_lang == "uz_cyrl":
        txt = (
            f"👤 **Сизнинг профилингиз:**

"
            f"👤 **Исм:** {message.from_user.first_name}
"
            f"🆔 **Telegram ID:** `{telegram_id}`
"
            f"💵 **Баланс:** {balance:,} сўм

"
            f"🔗 **Таклиф ҳаволангиз:**
"
            f"`https://t.me/EduStoreBot?start={ref_code}`"
        )
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🎟️ Промокод киритиш", callback_data="act_promo")],
            [types.InlineKeyboardButton(text="🌐 Тилни ўзгартириш", callback_data="act_lang")],
            [types.InlineKeyboardButton(text="💬 Қўллаб-қувватлаш", callback_data="act_support")]
        ])
    else:
        txt = (
            f"👤 **Ваш личный кабинет:**

"
            f"👤 **Имя:** {message.from_user.first_name}
"
            f"🆔 **Telegram ID:** `{telegram_id}`
"
            f"💵 **Баланс:** {balance:,} сум

"
            f"🔗 **Ваша реферальная ссылка:**
"
            f"`https://t.me/EduStoreBot?start={ref_code}`"
        )
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🎟️ Активировать промокод", callback_data="act_promo")],
            [types.InlineKeyboardButton(text="🌐 Сменить язык", callback_data="act_lang")],
            [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="act_support")]
        ])
        
    await message.answer(txt, reply_markup=kb, parse_mode="Markdown")


@router.message(Command("promocode"))
@router.message(F.text.in_(["🎟️ Промокод", "🎟️ Promokod"]))
@router.callback_query(F.data == "act_promo")
async def cmd_promocode(event: types.Message | types.CallbackQuery):
    msg = event.message if isinstance(event, types.CallbackQuery) else event
    txt = (
        "🎟️ **Активация промокода:**

"
        "Отправьте секретный промокод в чат (например: **WELCOME20** или **BONUS100K**), "
        "чтобы получить скидку на курсы или бонусы на баланс!"
    )
    if isinstance(event, types.CallbackQuery):
        await msg.answer(txt, parse_mode="Markdown")
        await event.answer()
    else:
        await msg.answer(txt, parse_mode="Markdown")


@router.message(Command("support"))
@router.message(Command("faq"))
@router.message(F.text.in_(["💬 Поддержка & FAQ", "💬 Поддержка", "💬 Yordam & FAQ", "💬 Qo'llab-quvvatlash", "💬 Ғордам & FAQ"]))
@router.callback_query(F.data == "act_support")
async def cmd_support(event: types.Message | types.CallbackQuery):
    msg = event.message if isinstance(event, types.CallbackQuery) else event
    txt = (
        "💬 **Служба поддержки и FAQ:**

"
        "❓ **Как зайти в закрытый Telegram-канал курса?**
"
        "Сразу после проведения оплаты бот генерирует индивидуальную одноразовую ссылку с лимитом на 1 человека.

"
        "📞 **Написать оператору поддержки:** @edustore_support"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💬 Написать в поддержку (@edustore_support)", url="https://t.me/edustore_support")]
    ])
    if isinstance(event, types.CallbackQuery):
        await msg.answer(txt, reply_markup=kb, parse_mode="Markdown")
        await event.answer()
    else:
        await msg.answer(txt, reply_markup=kb, parse_mode="Markdown")


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
            await message.answer(f"🎉 **Промокод '{code}' успешно применен!**

💰 На ваш баланс начислено **100 000 сум**!", parse_mode="Markdown")
            return
    elif "WELCOME" in code or "PROMO" in code or "SKIDKA" in code:
        await message.answer(f"🎉 **Промокод '{code}' успешно применен!**

Скидка **20%** применится автоматически при следующей покупке курса из каталога!", parse_mode="Markdown")
        return


@router.message(CommandStart())
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
    welcome_txt = (
        f"👋 **Здравствуйте, {message.from_user.first_name}!**\n\n"
        "Добро пожаловать в Академию Онлайн-Курсов.\n"
        "Здесь вы можете приобрести авторские курсы с моментальным доступом к урокам.\n\n"
        "Выберите нужное действие в меню ниже:"
    )

    await message.answer(welcome_txt, reply_markup=get_main_keyboard(user_lang), parse_mode="Markdown")
