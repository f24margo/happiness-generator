from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.models import get_or_create_user, update_user_field, can_generate
from core.locales import LOCALES

router = Router()

def get_main_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = LOCALES[lang]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["btn_warm"], callback_data="mood:warm"),
         InlineKeyboardButton(text=t["btn_wisdom"], callback_data="mood:wisdom")],
        [InlineKeyboardButton(text=t["btn_greed"], callback_data="mood:greed"),
         InlineKeyboardButton(text=t["btn_flattery"], callback_data="mood:flattery")],
        [InlineKeyboardButton(text=t["btn_lust"], callback_data="mood:lust")],
        [InlineKeyboardButton(text=t["btn_char"], callback_data="menu:chars"),
         InlineKeyboardButton(text=t["btn_lang"], callback_data="menu:langs")],
        [InlineKeyboardButton(text=t["btn_vip"], callback_data="menu:vip")]
    ])

def get_chars_keyboard(lang: str) -> InlineKeyboardMarkup:
    chars = LOCALES[lang]["chars"]
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"setchar:{code}")] for code, name in chars.items()]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_langs_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang:ru"),
         InlineKeyboardButton(text="��🇺🇦 Українська", callback_data="setlang:uk")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang:en"),
         InlineKeyboardButton(text="🇪🇸 Español", callback_data="setlang:es")]
    ])

@router.message(CommandStart())
async def cmd_start(message: Message):
    lang_code = (message.from_user.language_code or "ru")[:2]
    user = await get_or_create_user(message.from_user.id, message.from_user.username, lang_code)
    lang = user["language"]
    _, rem = await can_generate(user["user_id"])
    char_name = LOCALES[lang]["chars"].get(user["character_code"], "👩")

    await message.answer(
        f"{LOCALES[lang]['welcome']}\n\n" + LOCALES[lang]["menu_title"].format(char=char_name, rem=rem),
        reply_markup=get_main_keyboard(lang),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "menu:chars")
async def show_chars(callback: CallbackQuery):
    await callback.answer()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    lang = user["language"]
    await callback.message.answer(LOCALES[lang]["choose_char"], reply_markup=get_chars_keyboard(lang))

@router.callback_query(F.data.startswith("setchar:"))
async def set_char(callback: CallbackQuery):
    await callback.answer()
    char_code = callback.data.split(":", 1)[1]
    await update_user_field(callback.from_user.id, "character_code", char_code)
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    lang = user["language"]
    _, rem = await can_generate(user["user_id"])
    char_name = LOCALES[lang]["chars"].get(char_code, "👩")
    await callback.message.answer(
        LOCALES[lang]["menu_title"].format(char=char_name, rem=rem),
        reply_markup=get_main_keyboard(lang),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "menu:langs")
async def show_langs(callback: CallbackQuery):
    await callback.answer()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    await callback.message.answer(LOCALES[user["language"]]["choose_lang"], reply_markup=get_langs_keyboard())

@router.callback_query(F.data.startswith("setlang:"))
async def set_lang(callback: CallbackQuery):
    await callback.answer()
    lang = callback.data.split(":", 1)[1]
    await update_user_field(callback.from_user.id, "language", lang)
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    _, rem = await can_generate(user["user_id"])
    char_name = LOCALES[lang]["chars"].get(user["character_code"], "👩")
    await callback.message.answer(
        LOCALES[lang]["menu_title"].format(char=char_name, rem=rem),
        reply_markup=get_main_keyboard(lang),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "menu:vip")
async def show_vip(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    await callback.answer(LOCALES[user["language"]]["vip_info"], show_alert=True)
