from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.models import get_or_create_user, update_user_field, can_generate
from core.locales import LOCALES
from core.styles import STYLES, DEFAULT_STYLE

router = Router()

# Кнопка сборки промпта для своего ИИ (сама сборка пока на русском)
PROMPT_BTN = {
    "ru": "🎁 Промпт для своего ИИ",
    "uk": "🎁 Промпт для свого ШІ",
}

# Кнопка выбора стиля рисунка
STYLE_BTN = {
    "ru": "🎨 Стиль",
    "uk": "🎨 Стиль",
    "en": "🎨 Style",
    "es": "🎨 Estilo",
}

# Кнопка «Демо» (пока заглушка)
DEMO_BTN = {
    "ru": "💡 Демо (скоро)",
    "uk": "💡 Демо (незабаром)",
    "en": "💡 Demo (soon)",
    "es": "💡 Demo (pronto)",
}

DEMO_INFO = {
    "ru": "💡 Скоро здесь появятся примеры готовых шаржей в разных стилях.",
    "uk": "💡 Незабаром тут з'являться приклади готових шаржів у різних стилях.",
    "en": "💡 Examples of finished caricatures in different styles are coming soon.",
    "es": "💡 Pronto habrá ejemplos de caricaturas terminadas en distintos estilos.",
}

WELCOME = {
    "ru": (
        "✨ Добро пожаловать в <b>Генератор счастья</b>!\n\n"
        "📸 Пришлите своё фото или селфи, и я нарисую портрет или шарж в выбранном стиле.\n"
        "🎁 Или соберите запрос для своего ИИ: он нарисует у вас.\n\n"
        "Бесплатно сегодня: <b>{rem}</b>"
    ),
    "uk": (
        "✨ Ласкаво просимо до <b>Генератора щастя</b>!\n\n"
        "📸 Надішліть своє фото або селфі, і я намалюю портрет або шарж у вибраному стилі.\n"
        "🎁 Або зберіть запит для свого ШІ: він намалює у вас.\n\n"
        "Безкоштовно сьогодні: <b>{rem}</b>"
    ),
    "en": (
        "✨ Welcome to the <b>Happiness Generator</b>!\n\n"
        "📸 Send me your photo or a selfie and I'll draw a portrait or a caricature "
        "in the style you choose.\n\n"
        "Free today: <b>{rem}</b>"
    ),
    "es": (
        "✨ ¡Bienvenido al <b>Generador de Felicidad</b>!\n\n"
        "📸 Envíame tu foto o un selfie y dibujaré un retrato o una caricatura "
        "en el estilo que elijas.\n\n"
        "Gratis hoy: <b>{rem}</b>"
    ),
}

STALE_TEXT = {
    "ru": "Меню обновилось. Пришлите своё фото 📸 или выберите стиль.",
    "uk": "Меню оновилось. Надішліть своє фото 📸 або оберіть стиль.",
    "en": "The menu has been updated. Send your photo 📸 or choose a style.",
    "es": "El menú se actualizó. Envía tu foto 📸 o elige un estilo.",
}

# Выбранный стиль каждого человека. Хранится в памяти бота:
# после перезапуска у всех снова стиль по умолчанию.
USER_STYLES: dict[int, str] = {}


def get_user_style(user_id: int) -> str:
    code = USER_STYLES.get(user_id, DEFAULT_STYLE)
    return code if code in STYLES else DEFAULT_STYLE


def style_name(code: str, lang: str) -> str:
    names = STYLES[code]["names"]
    return names.get(lang) or names["ru"]


def menu_text(lang: str, rem) -> str:
    return WELCOME.get(lang, WELCOME["ru"]).format(rem=rem)


def get_main_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = LOCALES[lang]
    rows = [
        [InlineKeyboardButton(text=STYLE_BTN.get(lang, STYLE_BTN["ru"]), callback_data="menu:styles"),
         InlineKeyboardButton(text=t["btn_lang"], callback_data="menu:langs")],
    ]
    if lang in PROMPT_BTN:
        rows.append([InlineKeyboardButton(text=PROMPT_BTN[lang], callback_data="cfsm:start")])
    rows.append([
        InlineKeyboardButton(text=DEMO_BTN.get(lang, DEMO_BTN["ru"]), callback_data="menu:demo"),
        InlineKeyboardButton(text=t["btn_vip"], callback_data="menu:vip"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_styles_keyboard(lang: str, current: str) -> InlineKeyboardMarkup:
    rows = []
    for code in STYLES:
        mark = "✅ " if code == current else ""
        rows.append([InlineKeyboardButton(
            text=mark + style_name(code, lang),
            callback_data=f"setstyle:{code}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_langs_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang:ru"),
         InlineKeyboardButton(text="🇺🇦 Українська", callback_data="setlang:uk")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang:en"),
         InlineKeyboardButton(text="🇪🇸 Español", callback_data="setlang:es")]
    ])


@router.message(CommandStart())
async def cmd_start(message: Message):
    lang_code = (message.from_user.language_code or "ru")[:2]
    user = await get_or_create_user(message.from_user.id, message.from_user.username, lang_code)
    lang = user["language"]
    _, rem = await can_generate(user["user_id"])

    await message.answer(
        menu_text(lang, rem),
        reply_markup=get_main_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:langs")
async def show_langs(callback: CallbackQuery):
    await callback.answer()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    await callback.message.answer(LOCALES[user["language"]]["choose_lang"], reply_markup=get_langs_keyboard())


@router.callback_query(F.data.startswith("setlang:"))
async def set_lang(callback: CallbackQuery):
    lang = callback.data.split(":", 1)[1]
    if lang not in LOCALES:
        await callback.answer()
        return
    await callback.answer()
    await update_user_field(callback.from_user.id, "language", lang)
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    _, rem = await can_generate(user["user_id"])
    await callback.message.answer(
        menu_text(lang, rem),
        reply_markup=get_main_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:demo")
async def show_demo(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    lang = user["language"]
    await callback.answer(DEMO_INFO.get(lang, DEMO_INFO["ru"]), show_alert=True)


@router.callback_query(F.data == "menu:vip")
async def show_vip(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    await callback.answer(LOCALES[user["language"]]["vip_info"], show_alert=True)


@router.callback_query(F.data.startswith(("mood:", "setchar:")) | (F.data == "menu:chars"))
async def stale_menu_button(callback: CallbackQuery):
    """Кнопки из старых сообщений (настроения, смена героя): объясняем и показываем меню."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    lang = user["language"]
    await callback.message.answer(
        STALE_TEXT.get(lang, STALE_TEXT["ru"]),
        reply_markup=get_main_keyboard(lang),
    )