"""
aiogram 3 Catalog Handlers
Browse Categories, view Course cards, search courses, click Payme/Click checkout inline buttons.
"""
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import Category, Course

router = Router(name="catalog")


@router.message(F.text == "📚 Каталог курсов")
async def show_categories(message: types.Message, db: AsyncSession):
    stmt = select(Category)
    res = await db.execute(stmt)
    categories = res.scalars().all()

    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}")])
    keyboard.append([InlineKeyboardButton(text="🔍 Поиск курса", callback_data="search_course")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("📁 **Категории онлайн-курсов:**\nВыберите интересующую тему:", reply_markup=reply_markup, parse_mode="Markdown")


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
        caption = (
            f"🎓 <b>{c.title}</b>\n\n"
            f"{c.description[:200]}...\n\n"
            f"👤 Автор: {c.author}\n"
            f"💵 Цена: <b>{c.price_uzs:,} сум</b>\n"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить через Payme", callback_data=f"buy_payme_{c.id}")],
            [InlineKeyboardButton(text="🔹 Купить через Click", callback_data=f"buy_click_{c.id}")],
            [InlineKeyboardButton(text="⬅️ Назад в категории", callback_data="back_categories")]
        ])
        img = c.image_url if (c.image_url and c.image_url.startswith("http")) else default_cover
        try:
            await callback.message.answer_photo(photo=img, caption=caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.answer_photo(photo=default_cover, caption=caption, reply_markup=kb, parse_mode="HTML")

    await callback.answer()
