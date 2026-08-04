"""
aiogram 3 Start & Registration Handler
Supports referral link extraction (/start ref_123), user registration & main keyboard.
"""
import uuid
from aiogram import Router, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import User

router = Router(name="start")


def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Каталог курсов"), KeyboardButton(text="🎓 Мои курсы")],
            [KeyboardButton(text="👤 Личный кабинет"), KeyboardButton(text="🎟️ Промокод")],
            [KeyboardButton(text="💬 Поддержка & FAQ")]
        ],
        resize_keyboard=True
    )


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
            referred_by=ref_arg if ref_arg else None
        )
        db.add(user)
        await db.commit()

    welcome_txt = (
        f"👋 **Здравствуйте, {message.from_user.first_name}!**\n\n"
        "Добро пожаловать в Академию Онлайн-Курсов.\n"
        "Здесь вы можете приобрести авторские курсы с моментальным доступом к урокам.\n\n"
        "Выберите нужное действие в меню ниже:"
    )

    await message.answer(welcome_txt, reply_markup=get_main_keyboard(), parse_mode="Markdown")
