"""
Internationalization & Dynamic Dictionary Service for Telegram Bot
Handles RU, UZ (Lotin), UZ (Кирилл) phrases with dynamic overrides from DB.
"""
import json
import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import SystemSetting

logger = logging.getLogger(__name__)

DEFAULT_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "ru": {
        "welcome": "👋 Добро пожаловать в Академию Онлайн-Курсов!\nВыберите нужный раздел из меню ниже:",
        "selectLanguage": "🌐 Пожалуйста, выберите язык интерфейса:",
        "languageSet": "✅ Язык успешно изменен на Русский 🇷🇺!",
        "menuCatalog": "📚 Каталог курсов",
        "menuMyCourses": "🎓 Мои курсы",
        "menuProfile": "👤 Профиль и баланс",
        "menuReferral": "🎁 Реферальная система",
        "menuLanguage": "🌐 Сменить язык",
        "menuSupport": "💬 Поддержка & FAQ",
        "catalogTitle": "📂 Каталог доступных курсов:",
        "noCoursesFound": "Курсы в данной категории пока отсутствуют.",
        "price": "Цена:",
        "buyNow": "💳 Купить курс",
        "backToCatalog": "⬅️ Назад в каталог",
        "lessonsCount": "уроков",
        "checkoutTitle": "🛒 Оформление заказа",
        "choosePayment": "Выберите удобный способ оплаты:",
        "payWithPayme": "💳 Оплатить через Payme",
        "payWithClick": "🔹 Оплатить через Click",
        "enterPromoCode": "🎟️ Ввести промокод",
        "applyPromo": "Применить",
        "promoApplied": "✅ Промокод применен!",
        "promoInvalid": "❌ Неверный или истекший промокод.",
        "paymentSuccessTitle": "🎉 Оплата успешно завершена!",
        "singleUseLinkTitle": "🔒 Персональная одноразовая ссылка в закрытый Telegram-канал:",
        "enterPrivateChannel": "🔒 Войти в закрытый канал (1-разовая)",
        "singleUseNotice": "⚠️ Ссылка сгенерирована специально для вас и аннулируется после 1-го использования.",
        "profileTitle": "👤 Ваш профиль:",
        "yourBalance": "Баланс:",
        "topUpBalance": "💰 Пополнить баланс",
        "myCoursesTitle": "🎓 Ваши купленные курсы:",
        "noPurchasedCourses": "У вас пока нет купленных курсов. Выберите интересующий курс в каталоге!",
        "referralTitle": "🎁 Реферальная программа:",
        "referralBonusInfo": "Приглашайте друзей и получайте 10% от их покупок на свой баланс!",
        "yourRefLink": "Ваша реферальная ссылка:",
        "supportTitle": "💬 Служба поддержки и контакты:",
        "supportWelcome": "Добро пожаловать в центр поддержки и ответов на вопросы! Выберите нужный раздел или свяжитесь с оператором:",
        "supportOperator": "📞 Оператор поддержки:",
        "supportPhone": "📞 Телефон:",
        "faqBtnHowToJoin": "❓ Как получить доступ к курсу?",
        "faqBtnPaymentMethods": "💳 Способы оплаты (Payme / Click)",
        "faqBtnPromoCode": "🎟️ Как применить промокод?",
        "faqBtnReferral": "🎁 Реферальная программа",
        "faqBtnContactOperator": "💬 Написать оператору",
        "faqBtnInteractiveFaq": "📋 Открыть интерактивный FAQ",
        "faqAnswerHowToJoin": "❓ <b>Как моментально получить доступ к курсу?</b>\n\nПосле успешной оплаты через Payme или Click бот автоматически пришлет вам персонализированную 1-разовую ссылку (<code>member_limit=1</code>) в закрытый VIP Telegram-канал курса, а также откроет список уроков в разделе <b>Мои курсы</b>.",
        "faqAnswerPaymentMethods": "💳 <b>Способы оплаты:</b>\n\nИнтегрированы официальные платежные системы Узбекистана <b>Payme</b> (Merchant JSON-RPC) и <b>CLICK</b> (Merchant POST API). Все платежи обрабатываются мгновенно в автоматическом режиме с моментальной выдачей доступа.",
        "faqAnswerPromoCode": "🎟️ <b>Активация промокодов:</b>\n\nОтправьте секретный промокод (например, <b>WELCOME20</b> на скидку 20% или <b>BONUS100K</b> на +100 000 сум) прямым текстовым сообщением в чат боту!",
        "faqAnswerReferral": "🎁 <b>Реферальная система:</b>\n\nСкопируйте вашу уникальную реферальную ссылку в разделе <b>Профиль</b>. За каждый купленный курс вашим приглашенным другом вы получаете 10% от суммы на свой бонусный баланс!",
        "dbResetSuccess": "⚡ База данных успешно обнулена! Все заказы, логи и счетчики сброшены.",
    },
    "uz_latn": {
        "welcome": "👋 Onlayn-kurslar Akademiyasiga xush kelibsiz!\nQuyidagi menyudan kerakli bo'limni tanlang:",
        "selectLanguage": "🌐 Iltimos, interfeys tilini tanlang:",
        "languageSet": "✅ Til muvaffaqiyatli O'zbek tiliga (Lotin) o'zgartirildi 🇺🇿!",
        "menuCatalog": "📚 Kurslar katalogi",
        "menuMyCourses": "🎓 Mening kurslarim",
        "menuProfile": "👤 Profil va balans",
        "menuReferral": "🎁 Taklif tizimi (Bonus)",
        "menuLanguage": "🌐 Tilni o'zgartirish",
        "menuSupport": "💬 Yordam & FAQ",
        "catalogTitle": "📂 Mavjud kurslar katalogi:",
        "noCoursesFound": "Ushbu kategoriyada hozircha kurslar mavjud emas.",
        "price": "Narxi:",
        "buyNow": "💳 Kursni sotib olish",
        "backToCatalog": "⬅️ Katalogga qaytish",
        "lessonsCount": "ta dars",
        "checkoutTitle": "🛒 Buyurtmani rasmiylashtirish",
        "choosePayment": "Qulay to'lov usulini tanlang:",
        "payWithPayme": "💳 Payme orqali to'lash",
        "payWithClick": "🔹 Click orqali to'lash",
        "enterPromoCode": "🎟️ Promokod kiritish",
        "applyPromo": "Tasdiqlash",
        "promoApplied": "✅ Promokod qo'llanildi!",
        "promoInvalid": "❌ Promokod noto'g'ri yoki muddati o'tgan.",
        "paymentSuccessTitle": "🎉 To'lov muvaffaqiyatli yakunlandi!",
        "singleUseLinkTitle": "🔒 Yopiq Telegram-kanalga shaxsiy bir martalik havola:",
        "enterPrivateChannel": "🔒 Yopiq kanalga kirish (1 martalik)",
        "singleUseNotice": "⚠️ Havola maxsus siz uchun yaratilgan va 1 marta ishlatilgach bekor qilinadi.",
        "profileTitle": "👤 Sizning profilingiz:",
        "yourBalance": "Balans:",
        "topUpBalance": "💰 Balansni to'ldirish",
        "myCoursesTitle": "🎓 Siz sotib olgan kurslar:",
        "noPurchasedCourses": "Sizda hozircha sotib olingan kurslar yo'q. Katalogdan mos kursni tanlang!",
        "referralTitle": "🎁 Taklif va bonus tizimi:",
        "referralBonusInfo": "Do'stlaringizni taklif qiling va ularning xaridorligidan 10% bonus oling!",
        "yourRefLink": "Sizning taklif havolangiz:",
        "supportTitle": "💬 Qo'llab-quvvatlash va kontaktlar:",
        "supportWelcome": "Foydalanuvchilarga yordam markaziga xush kelibsiz! Kerakli bo'limni tanlang yoki operatorga murojaat qiling:",
        "supportOperator": "📞 Qo'llab-quvvatlash operatori:",
        "supportPhone": "📞 Telefon raqam:",
        "faqBtnHowToJoin": "❓ Kursga qanday kirish mumkin?",
        "faqBtnPaymentMethods": "💳 To'lov usullari (Payme / Click)",
        "faqBtnPromoCode": "🎟️ Promokoddan qanday foydalaniladi?",
        "faqBtnReferral": "🎁 Taklif va bonus tizimi",
        "faqBtnContactOperator": "💬 Operatorga yozish",
        "faqBtnInteractiveFaq": "📋 Interaktiv FAQ markazi",
        "faqAnswerHowToJoin": "❓ <b>Yopiq Telegram-kanalga qanday kiriladi?</b>\n\nPayme yoki Click orqali to'lov muvaffaqiyatli amalga oshirilgach, bot avtomatik ravishda shaxsiy bir martalik havolani (<code>member_limit=1</code>) yuboradi.",
        "faqAnswerPaymentMethods": "💳 <b>To'lov usullari:</b>\n\nBiz O'zbekistonning rasmiy to'lov tizimlari — <b>Payme</b> va <b>CLICK</b> ni qo'llab-quvvatlaymiz. Barcha to'lovlar avtomatik tarzda bir zumda tasdiqlanadi.",
        "faqAnswerPromoCode": "🎟️ <b>Promokodni faollashtirish:</b>\n\nPromokodingizni (masalan: <b>WELCOME20</b> yoki <b>BONUS100K</b>) bot chatiga to'g'ridan-to'g'ri xabar sifatida yuboring!",
        "faqAnswerReferral": "🎁 <b>Taklif (Referal) tizimi:</b>\n\n<b>Profil</b> bo'limidagi shaxsiy havolangizdan nusxa oling. Do'stlaringiz kurs xarid qilganda, uning 10% summasi sizning balansingizga tushadi!",
        "dbResetSuccess": "⚡ Ma'lumotlar bazasi to'liq tozalandi! Barcha buyurtmalar va loglar nolga tushirildi.",
    },
    "uz_cyrl": {
        "welcome": "👋 Онлайн-курслар Академиясига хуш келибсиз!\nҚуйидаги менюдан керакли бўлимни танланг:",
        "selectLanguage": "🌐 Илтимос, интерфейс тилини танланг:",
        "languageSet": "✅ Тил муваффақиятли Ўзбек тилига (Кирилл) ўзгартирилди 🇺🇿!",
        "menuCatalog": "📚 Курслар каталоги",
        "menuMyCourses": "🎓 Менинг курсларим",
        "menuProfile": "👤 Профиль ва баланс",
        "menuReferral": "🎁 Таклиф тизими (Бонус)",
        "menuLanguage": "🌐 Тилни ўзгартириш",
        "menuSupport": "💬 Қўллаб-қувватлаш & FAQ",
        "catalogTitle": "📂 Мавжуд курслар каталоги:",
        "noCoursesFound": "Ушбу категорияда ҳозирча курслар мавжуд эмас.",
        "price": "Нархи:",
        "buyNow": "💳 Курсни сотиб олиш",
        "backToCatalog": "⬅️ Каталогга қайтиш",
        "lessonsCount": "та дарс",
        "checkoutTitle": "🛒 Буюртмани расмийлаштириш",
        "choosePayment": "Қулай тўлов усулини танланг:",
        "payWithPayme": "💳 Payme орқали тўлаш",
        "payWithClick": "🔹 Click орқали тўлаш",
        "enterPromoCode": "🎟️ Промокод киритиш",
        "applyPromo": "Тасдиқлаш",
        "promoApplied": "✅ Промокод қўлланилди!",
        "promoInvalid": "❌ Промокод нотўғри ёки муддати ўтган.",
        "paymentSuccessTitle": "🎉 Тўлов муваффақиятли якунланди!",
        "singleUseLinkTitle": "🔒 Ёпиқ Telegram-каналга шахсий бир марталик ҳавола:",
        "enterPrivateChannel": "🔒 Ёпиқ каналга кириш (1 марталик)",
        "singleUseNotice": "⚠️ Ҳавола махсус сиз учун яратилган ва 1 марта ишлатилгач бекор қилинади.",
        "profileTitle": "👤 Сизнинг профилингиз:",
        "yourBalance": "Баланс:",
        "topUpBalance": "💰 Балансни тўлдириш",
        "myCoursesTitle": "🎓 Сиз сотиб олган курслар:",
        "noPurchasedCourses": "Сизда ҳозирча сотиб олинган курслар йўқ. Каталогдан мос курсни танланг!",
        "referralTitle": "🎁 Таклиф ва бонус тизими:",
        "referralBonusInfo": "Дўстларингизни таклиф қилинг ва уларнинг харидорлигидан 10% бонус олинг!",
        "yourRefLink": "Сизнинг таклиф ҳаволангиз:",
        "supportTitle": "💬 Қўллаб-қувватлаш ва контактлар:",
        "supportWelcome": "Фойдаланувчиларга ёрдам марказига хуш келибсиз! Керакли бўлимни танланг ёки операторга мурожаат қилинг:",
        "supportOperator": "📞 Қўллаб-қувватлаш оператори:",
        "supportPhone": "📞 Телефон рақам:",
        "faqBtnHowToJoin": "❓ Курсга қандай кириш мумкин?",
        "faqBtnPaymentMethods": "💳 Тўлов усуллари (Payme / Click)",
        "faqBtnPromoCode": "🎟️ Промокоддан қандай фойдаланилади?",
        "faqBtnReferral": "🎁 Таклиф ва бонус тизими",
        "faqBtnContactOperator": "💬 Операторга ёзиш",
        "faqBtnInteractiveFaq": "📋 Интерактив FAQ маркази",
        "faqAnswerHowToJoin": "❓ <b>Ёпиқ Telegram-каналга қандай кирилади?</b>\n\nPayme ёки Click орқали тўлов муваффақиятли амалга оширилгач, бот автоматик равишда шахсий бир марталик ҳаволани (<code>member_limit=1</code>) юборади.",
        "faqAnswerPaymentMethods": "💳 <b>Тўлов усуллари:</b>\n\nБиз Ўзбекистоннинг расмий тўлов тизимлари — <b>Payme</b> ва <b>CLICK</b> ни қўллаб-қувватлаймиз. Барча тўловлар автоматик тарзда бир зумда тасдиқланади.",
        "faqAnswerPromoCode": "🎟️ <b>Промокодни фаоллаштириш:</b>\n\nПромокодингизни (масалан: <b>WELCOME20</b> ёки <b>BONUS100K</b>) бот чатига тўғридан-тўғри хабар сифатида юборинг!",
        "faqAnswerReferral": "🎁 <b>Таклиф (Реферал) тизими:</b>\n\n<b>Профиль</b> бўлимидаги шахсий ҳаволангиздан нусха олинг. Дўстларингиз курс харид қилганда, унинг 10% суммаси сизнинг балансингизга тушади!",
        "dbResetSuccess": "⚡ Маълумотлар базаси тўлиқ тозаланди! Барча буюртмалар ва логлар нолга туширилди.",
    }
}

CATEGORY_GROUPS = [
    {
        "name": "🚀 Приветствия & Навигация",
        "keys": ["welcome", "selectLanguage", "languageSet", "dbResetSuccess"],
    },
    {
        "name": "🔘 Кнопки Главного Меню",
        "keys": ["menuCatalog", "menuMyCourses", "menuProfile", "menuReferral", "menuLanguage", "menuSupport"],
    },
    {
        "name": "📚 Каталог & Карточки Курсов",
        "keys": ["catalogTitle", "noCoursesFound", "price", "buyNow", "backToCatalog", "lessonsCount"],
    },
    {
        "name": "💳 Оформление Заказа & Оплата",
        "keys": ["checkoutTitle", "choosePayment", "payWithPayme", "payWithClick", "enterPromoCode", "applyPromo", "promoApplied", "promoInvalid"],
    },
    {
        "name": "🔒 Ссылки Доступа & Канал",
        "keys": ["paymentSuccessTitle", "singleUseLinkTitle", "enterPrivateChannel", "singleUseNotice"],
    },
    {
        "name": "👤 Профиль & Реферальная Система",
        "keys": ["profileTitle", "yourBalance", "topUpBalance", "myCoursesTitle", "noPurchasedCourses", "referralTitle", "referralBonusInfo", "yourRefLink"],
    },
    {
        "name": "💬 Поддержка, FAQ & Кнопки помощи",
        "keys": [
            "supportTitle",
            "supportWelcome",
            "supportOperator",
            "supportPhone",
            "faqBtnHowToJoin",
            "faqBtnPaymentMethods",
            "faqBtnPromoCode",
            "faqBtnReferral",
            "faqBtnContactOperator",
            "faqBtnInteractiveFaq",
            "faqAnswerHowToJoin",
            "faqAnswerPaymentMethods",
            "faqAnswerPromoCode",
            "faqAnswerReferral"
        ],
    },
]


async def get_active_dictionary(db: AsyncSession) -> Dict[str, Dict[str, str]]:
    """Loads dictionary merged with database overrides"""
    dictionary = {
        "ru": dict(DEFAULT_TRANSLATIONS["ru"]),
        "uz_latn": dict(DEFAULT_TRANSLATIONS["uz_latn"]),
        "uz_cyrl": dict(DEFAULT_TRANSLATIONS["uz_cyrl"])
    }
    try:
        stmt = select(SystemSetting).where(SystemSetting.key == "custom_dictionary_json")
        res = await db.execute(stmt)
        custom_row = res.scalar_one_or_none()
        if custom_row and custom_row.value:
            overrides = json.loads(custom_row.value)
            for lang in ["ru", "uz_latn", "uz_cyrl"]:
                if lang in overrides and isinstance(overrides[lang], dict):
                    dictionary[lang].update(overrides[lang])
    except Exception as e:
        logger.warning(f"Error loading custom dictionary JSON from DB: {e}")
    return dictionary


async def get_phrase(key: str, lang: str = "ru", db: Optional[AsyncSession] = None) -> str:
    """Gets single phrase by key and language"""
    if db:
        d = await get_active_dictionary(db)
        return d.get(lang, {}).get(key) or d.get("ru", {}).get(key) or DEFAULT_TRANSLATIONS.get(lang, {}).get(key, key)
    return DEFAULT_TRANSLATIONS.get(lang, {}).get(key) or DEFAULT_TRANSLATIONS.get("ru", {}).get(key, key)
