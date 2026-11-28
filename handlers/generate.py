import asyncio
import html
import io
import logging
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.captions import CAPTION_GENRES
from core.locales import LOCALES
from core.styles import STYLES
from database.models import can_generate, get_or_create_user, increment_usage
from handlers.caricature_prompt import (
    CARICATURE_LEVELS,
    MODES,
    PORTRAIT_LEVELS,
    SCENES,
)
from handlers.start import (
    PROMPT_BTN,
    STYLE_BTN,
    USER_STYLES,
    get_main_keyboard,
    get_styles_keyboard,
    get_user_style,
    style_name,
)
from services.ai_service import DEFAULT_SETTINGS, QuotaExceeded, generate_by_settings

logger = logging.getLogger(__name__)
router = Router()


class SetFSM(StatesGroup):
    exclude_text = State()
    topic_text = State()


# Фото, которое человек прислал: {user_id: file_id}
PENDING_PHOTOS: dict[int, str] = {}
# Настройки рисования каждого человека (хранятся в памяти бота)
USER_SETTINGS: dict[int, dict] = {}
# Кто сейчас рисуется (защита от двойного нажатия)
BUSY_USERS: set[int] = set()

SETTING_KEYS = ("mode", "level", "scene", "exclude", "caption", "topic")

# ---------------- Тексты ----------------
PHOTO_EXPIRED = {
    "ru": "Фото уже не помню. Пришлите его ещё раз 📸",
    "uk": "Фото вже не пам'ятаю. Надішліть його ще раз 📸",
    "en": "I no longer have that photo. Please send it again 📸",
    "es": "Ya no tengo esa foto. Envíala de nuevo 📸",
}

BUSY_TEXT = {
    "ru": "Уже рисую, подождите минуту 🎨",
    "uk": "Вже малюю, зачекайте хвилину 🎨",
    "en": "Already drawing, give me a minute 🎨",
    "es": "Ya estoy dibujando, espera un minuto 🎨",
}

DRAWING_TEXT = {
    "ru": "🎨 Рисую. Это займёт около минуты...",
    "uk": "🎨 Малюю. Це займе близько хвилини...",
    "en": "🎨 Drawing. This takes about a minute...",
    "es": "🎨 Dibujando. Tardará cerca de un minuto...",
}

DRAW_BTN = {
    "ru": "🎨 Рисовать",
    "uk": "🎨 Малювати",
    "en": "🎨 Draw",
    "es": "🎨 Dibujar",
}

AGAIN_BTN = {
    "ru": "🔄 Другой вариант",
    "uk": "🔄 Інший варіант",
    "en": "🔄 Another version",
    "es": "🔄 Otra versión",
}

EDIT_BTN = {
    "ru": "⚙️ Изменить",
    "uk": "⚙️ Змінити",
    "en": "⚙️ Change",
    "es": "⚙️ Cambiar",
}

QUOTA_TEXT = {
    "ru": "🎨 Бесплатные картинки на сегодня закончились. Они обновятся позже, попробуйте через некоторое время. Ваш лимит не потрачен.",
    "uk": "🎨 Безкоштовні картинки на сьогодні закінчилися. Вони оновляться пізніше, спробуйте згодом. Ваш ліміт не витрачено.",
    "en": "🎨 Today's free drawings are used up. They refresh later, try again in a while. Your limit was not spent.",
    "es": "🎨 Los dibujos gratuitos de hoy se agotaron. Se renuevan más tarde, inténtalo de nuevo. Tu límite no se gastó.",
}

QUOTA_HINT = {
    "ru": "\n\n🎁 А пока можно собрать запрос и нарисовать в своём ИИ: кнопка ниже.",
    "uk": "\n\n🎁 А поки можна зібрати запит і намалювати у своєму ШІ: кнопка нижче.",
}

CHOOSE_STYLE = {
    "ru": "🎨 Выберите стиль рисунка:",
    "uk": "🎨 Оберіть стиль малюнка:",
    "en": "🎨 Choose the drawing style:",
    "es": "🎨 Elige el estilo del dibujo:",
}

STYLE_SET = {
    "ru": "Стиль выбран: {name}.",
    "uk": "Стиль обрано: {name}.",
    "en": "Style selected: {name}.",
    "es": "Estilo elegido: {name}.",
}

MENU_HINT = {
    "ru": "Пришлите своё фото или селфи 📸",
    "uk": "Надішліть своє фото або селфі 📸",
    "en": "Send your photo or a selfie 📸",
    "es": "Envía tu foto o un selfie 📸",
}

TEXT_MODE = "⚙️ <b>Настройки рисунка</b>\nШаг 1. <b>Что рисуем?</b>"
TEXT_LEVEL_PORTRAIT = (
    "Шаг 3 из 4. <b>Насколько обрабатывать лицо?</b>\n"
    "Чем больше обработки, тем слабее сходство с фото."
)
TEXT_LEVEL_CARICATURE = (
    "Шаг 3 из 5. <b>Какой силы шарж?</b>\n"
    "От мягкого гротеска до доброй сатиры."
)
TEXT_EXCLUDE = (
    "Шаг 3 из 5. <b>Что не преувеличивать?</b>\n"
    "Напишите одним-двумя словами (например: уши, лоб) или нажмите кнопку."
)
TEXT_CAPTION = (
    "Шаг 5 из 5. <b>Подпись к картинке.</b>\n"
    "Выберите жанр текста. Он появится под картинкой."
)
TEXT_TOPIC = (
    "<b>Тема, повод или имя</b> (необязательно).\n"
    "Например: «про деньги» или «Анна, юбилей 60 лет». Или нажмите кнопку."
)


def _total(mode: str | None) -> int:
    return 5 if mode == "caricature" else 4


def _text_style(mode: str | None) -> str:
    return f"Шаг 2 из {_total(mode)}. <b>В каком стиле?</b>"


def _text_scene(mode: str | None) -> str:
    return f"Шаг 4 из {_total(mode)}. <b>Сцена и фон.</b>\nВыберите вариант."


# ---------------- Настройки ----------------
def _levels(mode: str | None) -> dict:
    return PORTRAIT_LEVELS if mode == "portrait" else CARICATURE_LEVELS


def _default_level(mode: str | None) -> str:
    return "asphoto" if mode == "portrait" else "soft"


def get_settings(user_id: int) -> dict:
    s = {**DEFAULT_SETTINGS, **USER_SETTINGS.get(user_id, {})}
    s["style"] = get_user_style(user_id)
    if s.get("mode") not in MODES:
        s["mode"] = DEFAULT_SETTINGS["mode"]
    if s.get("level") not in _levels(s["mode"]):
        s["level"] = _default_level(s["mode"])
    if s.get("scene") not in SCENES:
        s["scene"] = "plain"
    if s.get("caption") not in CAPTION_GENRES or s["mode"] == "portrait":
        s["caption"] = "none"
    return s


def update_settings(user_id: int, **changes) -> dict:
    if len(USER_SETTINGS) > 5000:
        USER_SETTINGS.clear()
    current = {k: get_settings(user_id).get(k) for k in SETTING_KEYS}
    current.update(changes)
    USER_SETTINGS[user_id] = current
    return get_settings(user_id)


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())[:120]


def card_text(lang: str, s: dict, intro: str) -> str:
    mode = "Портрет" if s["mode"] == "portrait" else "Шарж"
    level_label = _levels(s["mode"])[s["level"]]["label"]
    level_title = "Обработка" if s["mode"] == "portrait" else "Сила"
    lines = [
        intro,
        "",
        "<b>Сейчас выбрано:</b>",
        f"• Режим: {mode}",
        f"• Стиль: {style_name(s['style'], lang)}",
        f"• {level_title}: {level_label}",
        f"• Сцена: {SCENES[s['scene']]['label']}",
    ]
    if s["mode"] == "caricature":
        lines.append(f"• Подпись: {CAPTION_GENRES[s['caption']]['label']}")
        if s.get("exclude"):
            lines.append(f"• Не преувеличивать: {html.escape(s['exclude'], quote=False)}")
        if s["caption"] != "none" and s.get("topic"):
            lines.append(f"• Тема: {html.escape(s['topic'], quote=False)}")
    return "\n".join(lines)


def card_kb(lang: str, again: bool = False) -> InlineKeyboardMarkup:
    draw = (AGAIN_BTN if again else DRAW_BTN).get(lang) or (AGAIN_BTN if again else DRAW_BTN)["ru"]
    rows = [
        [
            InlineKeyboardButton(text=draw, callback_data="gdraw:go"),
            InlineKeyboardButton(text=EDIT_BTN.get(lang, EDIT_BTN["ru"]), callback_data="gset:start"),
        ],
        [
            InlineKeyboardButton(text=STYLE_BTN.get(lang, STYLE_BTN["ru"]), callback_data="menu:styles"),
            InlineKeyboardButton(text=LOCALES[lang]["btn_lang"], callback_data="menu:langs"),
        ],
    ]
    if lang in PROMPT_BTN:
        rows.append([InlineKeyboardButton(text=PROMPT_BTN[lang], callback_data="cfsm:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _quota_message(lang: str) -> str:
    return QUOTA_TEXT.get(lang, QUOTA_TEXT["ru"]) + QUOTA_HINT.get(lang, "")


# ---------------- Клавиатуры шагов ----------------
def _cancel_row() -> list:
    return [InlineKeyboardButton(text="✖ Назад к рисованию", callback_data="gset:done")]


def _modes_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"gset:mode:{code}")]
        for code, label in MODES.items()
    ]
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _styles_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=style_name(code, "ru"), callback_data=f"gset:style:{code}")]
        for code in STYLES
    ]
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _levels_kb(levels: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=v["label"], callback_data=f"gset:lvl:{k}")]
        for k, v in levels.items()
    ]
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _exclude_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Ничего, дальше", callback_data="gset:skipx")],
        _cancel_row(),
    ])


def _scenes_kb() -> InlineKeyboardMarkup:
    items = list(SCENES.items())
    rows = []
    for i in range(0, len(items), 2):
        rows.append([
            InlineKeyboardButton(text=v["label"], callback_data=f"gset:scene:{k}")
            for k, v in items[i:i + 2]
        ])
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _captions_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=v["label"], callback_data=f"gset:cap:{k}")]
        for k, v in CAPTION_GENRES.items()
    ]
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _topic_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Без темы, дальше", callback_data="gset:skipt")],
        _cancel_row(),
    ])


async def _show(target, text: str, kb=None) -> None:
    """Показывает шаг: правит то же сообщение; если нельзя (например, это картинка), шлёт новое."""
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
        await target.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


async def _show_card(target, user_id: int, intro: str | None = None) -> None:
    user = await get_or_create_user(user_id, None)
    lang = user["language"]
    s = get_settings(user_id)
    text = card_text(lang, s, intro or "✅ <b>Настройки сохранены.</b> Нажмите «Рисовать».")
    await _show(target, text, card_kb(lang))


# ---------------- Стили (кнопка «Стиль») ----------------
@router.callback_query(F.data == "menu:styles")
async def show_styles(callback: CallbackQuery):
    await callback.answer()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    lang = user["language"]
    current = get_user_style(user["user_id"])
    await callback.message.answer(
        CHOOSE_STYLE.get(lang, CHOOSE_STYLE["ru"]),
        reply_markup=get_styles_keyboard(lang, current),
    )


@router.callback_query(F.data.startswith("setstyle:"))
async def set_style(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    if code not in STYLES:
        await callback.answer()
        return

    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    lang = user["language"]
    user_id = user["user_id"]

    if len(USER_STYLES) > 5000:
        USER_STYLES.clear()
    USER_STYLES[user_id] = code
    await callback.answer()

    text = STYLE_SET.get(lang, STYLE_SET["ru"]).format(name=style_name(code, lang))
    if user_id in PENDING_PHOTOS:
        await _show_card(callback.message, user_id, "✅ " + text)
    else:
        await callback.message.answer(
            text + "\n\n" + MENU_HINT.get(lang, MENU_HINT["ru"]),
            reply_markup=get_main_keyboard(lang),
        )


# ---------------- Фото ----------------
@router.message(F.photo)
async def handle_photo_received(message: Message, state: FSMContext):
    """Фото пришло: запоминаем и показываем карточку с настройками."""
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    lang = user["language"]
    user_id = user["user_id"]

    allowed, _ = await can_generate(user_id)
    if not allowed:
        await message.answer(LOCALES[lang]["limit_reached"])
        return

    if len(PENDING_PHOTOS) > 500:
        PENDING_PHOTOS.clear()
    PENDING_PHOTOS[user_id] = message.photo[-1].file_id

    s = get_settings(user_id)
    await message.answer(
        card_text(lang, s, "📸 <b>Фото получено!</b> Нажмите «Рисовать» или измените настройки."),
        parse_mode="HTML",
        reply_markup=card_kb(lang),
    )


@router.callback_query(F.data.startswith("pmood:"))
async def old_photo_buttons(callback: CallbackQuery):
    """Кнопки настроений из старых сообщений: показываем карточку."""
    await callback.answer()
    user_id = callback.from_user.id
    if user_id in PENDING_PHOTOS:
        await _show_card(callback.message, user_id, "Меню обновилось. Проверьте настройки и нажмите «Рисовать».")
    else:
        user = await get_or_create_user(user_id, callback.from_user.username)
        lang = user["language"]
        await callback.message.answer(
            MENU_HINT.get(lang, MENU_HINT["ru"]),
            reply_markup=get_main_keyboard(lang),
        )


# ---------------- Рисование ----------------
@router.callback_query(F.data == "gdraw:go")
async def draw(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    lang = user["language"]
    user_id = user["user_id"]

    file_id = PENDING_PHOTOS.get(user_id)
    if not file_id:
        await callback.answer(PHOTO_EXPIRED.get(lang, PHOTO_EXPIRED["ru"]), show_alert=True)
        return

    if user_id in BUSY_USERS:
        await callback.answer(BUSY_TEXT.get(lang, BUSY_TEXT["ru"]), show_alert=True)
        return

    allowed, _ = await can_generate(user_id)
    if not allowed:
        await callback.answer(LOCALES[lang]["limit_reached"], show_alert=True)
        return

    await callback.answer()
    BUSY_USERS.add(user_id)
    status_msg = await callback.message.answer(DRAWING_TEXT.get(lang, DRAWING_TEXT["ru"]))
    settings = get_settings(user_id)

    try:
        bot: Bot = callback.bot
        photo_file = await asyncio.wait_for(bot.get_file(file_id), timeout=15.0)
        buf = io.BytesIO()
        await asyncio.wait_for(bot.download_file(photo_file.file_path, buf), timeout=20.0)

        caption, img_bytes = await asyncio.wait_for(
            generate_by_settings(lang, buf.getvalue(), settings),
            timeout=100.0,
        )
        if img_bytes:
            out_photo = BufferedInputFile(img_bytes, filename="picture.jpg")
            sent = await callback.message.answer_photo(
                photo=out_photo,
                caption=caption or None,
                reply_markup=card_kb(lang, again=True),
            )
            used_mode = f"{settings['mode']}:{settings['level']}"[:30]
            await increment_usage(user_id, "custom_photo", used_mode, True, sent.photo[-1].file_id)
        else:
            await callback.message.answer(
                "🎨 Картинка не получилась. Нажмите «Рисовать» ещё раз.",
                reply_markup=card_kb(lang),
            )
    except QuotaExceeded:
        await callback.message.answer(_quota_message(lang), reply_markup=card_kb(lang))
    except asyncio.TimeoutError:
        logger.error("Timeout during drawing for user %s", user_id)
        await callback.message.answer(
            "⏳ Рисование заняло слишком много времени. Нажмите «Рисовать» ещё раз!",
            reply_markup=card_kb(lang),
        )
    except Exception as e:
        logger.exception("Drawing error: %s", e)
        await callback.message.answer(
            "⏳ Сервер перегружен, нажмите «Рисовать» ещё раз через пару секунд!",
            reply_markup=card_kb(lang),
        )
    finally:
        BUSY_USERS.discard(user_id)
        with suppress(Exception):
            await status_msg.delete()


# ---------------- Настройки (шаги) ----------------
@router.callback_query(F.data == "gset:start")
async def set_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _show(callback, TEXT_MODE, _modes_kb())


@router.callback_query(F.data == "gset:done")
async def set_done(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _show_card(callback, callback.from_user.id, "Настройки без изменений.")


@router.callback_query(F.data.startswith("gset:mode:"))
async def set_mode(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    mode = callback.data.split(":", 2)[2]
    if mode not in MODES:
        return
    await state.clear()
    changes = {"mode": mode, "level": _default_level(mode)}
    if mode == "portrait":
        changes.update(caption="none", exclude="", topic="")
    update_settings(callback.from_user.id, **changes)
    await _show(callback, _text_style(mode), _styles_kb())


@router.callback_query(F.data.startswith("gset:style:"))
async def set_style_step(callback: CallbackQuery):
    await callback.answer()
    code = callback.data.split(":", 2)[2]
    if code not in STYLES:
        return
    user_id = callback.from_user.id
    if len(USER_STYLES) > 5000:
        USER_STYLES.clear()
    USER_STYLES[user_id] = code
    s = get_settings(user_id)
    if s["mode"] == "portrait":
        await _show(callback, TEXT_LEVEL_PORTRAIT, _levels_kb(PORTRAIT_LEVELS))
    else:
        await _show(callback, TEXT_LEVEL_CARICATURE, _levels_kb(CARICATURE_LEVELS))


@router.callback_query(F.data.startswith("gset:lvl:"))
async def set_level(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id
    s = get_settings(user_id)
    if key not in _levels(s["mode"]):
        return
    update_settings(user_id, level=key)
    if s["mode"] == "caricature":
        await state.set_state(SetFSM.exclude_text)
        await _show(callback, TEXT_EXCLUDE, _exclude_kb())
    else:
        await _show(callback, _text_scene(s["mode"]), _scenes_kb())


@router.callback_query(SetFSM.exclude_text, F.data == "gset:skipx")
async def skip_exclude(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    update_settings(callback.from_user.id, exclude="")
    await _show(callback, _text_scene("caricature"), _scenes_kb())


@router.message(SetFSM.exclude_text, F.text & ~F.text.startswith("/"))
async def typed_exclude(message: Message, state: FSMContext):
    await state.clear()
    update_settings(message.from_user.id, exclude=_clean(message.text))
    await message.answer(_text_scene("caricature"), parse_mode="HTML", reply_markup=_scenes_kb())


@router.callback_query(F.data.startswith("gset:scene:"))
async def set_scene(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    if key not in SCENES:
        return
    user_id = callback.from_user.id
    s = update_settings(user_id, scene=key)
    if s["mode"] == "caricature":
        await _show(callback, TEXT_CAPTION, _captions_kb())
    else:
        await _show_card(callback, user_id)


@router.callback_query(F.data.startswith("gset:cap:"))
async def set_caption(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    if key not in CAPTION_GENRES:
        return
    user_id = callback.from_user.id
    if key == "none":
        await state.clear()
        update_settings(user_id, caption="none", topic="")
        await _show_card(callback, user_id)
        return
    update_settings(user_id, caption=key)
    await state.set_state(SetFSM.topic_text)
    await _show(callback, TEXT_TOPIC, _topic_kb())


@router.callback_query(SetFSM.topic_text, F.data == "gset:skipt")
async def skip_topic(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    update_settings(callback.from_user.id, topic="")
    await _show_card(callback, callback.from_user.id)


@router.message(SetFSM.topic_text, F.text & ~F.text.startswith("/"))
async def typed_topic(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    update_settings(user_id, topic=_clean(message.text))
    await _show_card(message, user_id)


@router.callback_query(F.data.startswith("gset:"))
async def stale_settings_button(callback: CallbackQuery, state: FSMContext):
    """Кнопка из старого сообщения или потерянный шаг: показываем карточку."""
    await callback.answer()
    await state.clear()
    if callback.from_user.id in PENDING_PHOTOS:
        await _show_card(callback.message, callback.from_user.id, "Шаг потерялся. Проверьте настройки.")
    else:
        user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
        lang = user["language"]
        await callback.message.answer(
            MENU_HINT.get(lang, MENU_HINT["ru"]),
            reply_markup=get_main_keyboard(lang),
        )