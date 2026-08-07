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
