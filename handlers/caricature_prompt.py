import html
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.captions import CAPTION_GENRES, caption_request
from core.styles import STYLES, style_technique_prompt

router = Router()


class PromptFSM(StatesGroup):
    exclude_text = State()
    scene_text = State()
    caption_topic = State()


# ---------- Режимы ----------
MODES = {
    "portrait": "🖼 Портрет: максимально похоже на фото",
    "caricature": "🎭 Шарж: от мягкого гротеска до доброй сатиры",
}

# ---------- Ступени ----------
PORTRAIT_LEVELS = {
    "asphoto": {
        "label": "📷 Как на фото",
        "text": (
            "Keep the likeness exact: {keep}. "
            "Do not retouch and do not make the person look younger or older."
        ),
    },
    "retouch": {
        "label": "✨ Лёгкая ретушь",
        "text": (
            "Keep the likeness exact: {keep}. "
            "Apply only a light retouch: softer lighting, remove accidental shadows "
            "and blemishes, keep the real wrinkles and age."
        ),
    },
    "warm": {
        "label": "😊 Тёплый взгляд, лёгкая улыбка",
        "text": (
            "Keep the likeness exact: {keep}. "
            "Make the expression slightly warmer: a gentle natural smile and a kind look. "
            "Do not change the age."
        ),
    },
}

CARICATURE_LEVELS = {
    "soft": {
        "label": "🙂 Мягкий гротеск",
        "text": (
            "Keep the person clearly recognizable. "
            "Choose the 2-3 most distinctive facial features yourself and exaggerate them gently; "
            "make the head slightly larger than the body. Kind, friendly expression."
        ),
    },
    "fun": {
        "label": "😄 Весёлый шарж",
        "text": (
            "Keep the person clearly recognizable. "
            "Choose the 2-3 most distinctive facial features yourself and exaggerate them noticeably; "
            "use a lively, expressive face and a clearly larger head."
        ),
    },
    "satire": {
        "label": "🎭 Добрая сатира",
        "text": (
            "Keep the person clearly recognizable. "
            "Choose the 2-3 most distinctive facial features yourself and exaggerate them noticeably. "
            "Add a simple prop or detail that kindly mocks a human trait such as greed, flattery "
            "or self-importance; aim the joke at the behavior, never at the person's body, age or looks."
        ),
    },
}

# ---------- Сцены ----------
SCENES = {
    "plain": {"label": "⬜ Простой фон", "text": None},
    "desk": {
        "label": "💻 За столом с ноутбуком",
        "text": "sitting at a desk with a laptop and a cup of coffee, warm cozy light",
    },
    "home": {
        "label": "🏡 Дома с чашкой чая",
        "text": "in a cozy home interior with a cup of tea, calm kind mood",
    },
    "books": {
        "label": "📚 Среди книг",
        "text": "in a study with shelves of books, holding an open book",
    },
    "garden": {
        "label": "🌿 В саду",
        "text": "in a blooming garden on a sunny day",
    },
    "piggy": {
        "label": "💰 С копилкой",
        "text": "hugging a giant piggy bank and a heap of gold coins with a sly smirk",
    },
    "crown": {
        "label": "👑 С короной",
        "text": "holding a golden crown with an over-sweet smile, one hand behind the back with fingers crossed",
    },
    "rose": {
        "label": "🌹 С розой",
        "text": "holding a single rose with a charming wink and a playful smile, fully dressed",
    },
    "dynamic": {
        "label": "⚡ Яркий фон и драйв",
        "text": "on a bold expressive abstract background with dynamic energy",
    },
}

KEEP_PLAIN = "same pose, same angle, same expression, same clothing and hairstyle"
KEEP_SCENE = "same face, same head angle, same expression and hairstyle"
PLAIN_SENTENCE = "Plain simple background, no scene and no props."

RULES = (
    "Draw glasses, wrinkles and facial hair only if they are visible in the photo; "
    "if the person wears no glasses, draw no glasses. "
    "The gaze is directed straight at the viewer. "
    "Render the whole picture strictly in this style. "
    "No text, no letters, no signs, no signature inside the image."
)

# ---------- Фразы-поправки (для отправки ИИ следующим сообщением) ----------
COMMON_FIXES = [
    ("Очки", [
        "Add the glasses exactly as in the photo.",
        "Remove the glasses: the person does not wear them.",
    ]),
    ("Взгляд", ["Make the gaze look straight at the viewer."]),
    ("Надписи", ["Remove all text and letters from the image."]),
    ("Сходство", ["Make the face more similar to the person in the photo."]),
]
PORTRAIT_FIXES = COMMON_FIXES + [
    ("Обработка", ["Less retouching: keep the wrinkles and details exactly as in the photo."]),
]
CARICATURE_FIXES = COMMON_FIXES + [
    ("Сила шаржа", [
        "Exaggerate the distinctive features a bit more.",
        "Reduce the exaggeration and keep it closer to the photo.",
    ]),
    ("Подпись", [
        "Make the caption shorter.",
        "Make the caption funnier.",
    ]),
]

# ---------- Тексты шагов ----------
TEXT_MODE = (
    "🎁 <b>Промпт для вашего ИИ</b>\n"
    "Шаг 1. <b>Что рисуем?</b>\n\n"
    "Фото я не вижу и не храню: вы прикрепите его у себя, в своём ИИ (Gemini, ChatGPT и др.)."
)
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
    "Напишите одним-двумя словами (например: уши, лоб) или нажмите «Пропустить»."
)
TEXT_CAPTION = (
    "Шаг 5 из 5. <b>Подпись к картинке.</b>\n"
    "Выберите жанр текста. ИИ напишет его отдельным сообщением, не на самой картинке."
)
TEXT_TOPIC = (
    "<b>Тема, повод или имя</b> (необязательно).\n"
    "Например: «про деньги» или «Анна, юбилей 60 лет». Или нажмите «Пропустить»."
)
TEXT_ASK_SCENE = (
    "Опишите сцену своими словами, одной строкой "
    "(например: «на рыбалке с большой рыбой»)."
)
TEXT_RESTART = "Бот обновлялся, начнём заново.\n\n"


def _total(mode: str | None) -> int:
    return 5 if mode == "caricature" else 4


def _text_style(mode: str | None) -> str:
    return f"Шаг 2 из {_total(mode)}. <b>В каком стиле?</b>"


def _text_scene(mode: str | None) -> str:
    return f"Шаг 4 из {_total(mode)}. <b>Сцена и фон.</b>\nВыберите вариант или опишите свой."


# ---------- Вспомогательные функции ----------
def _cancel_row() -> list:
    return [InlineKeyboardButton(text="✖ Отмена", callback_data="cfsm:cancel")]


def _style_name(code: str) -> str:
    names = STYLES[code].get("names", {})
    return names.get("ru") or next(iter(names.values()), code)


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())[:120]


def _modes_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"cfsm:mode:{code}")]
        for code, label in MODES.items()
    ]
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _styles_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_style_name(code), callback_data=f"cfsm:style:{code}")]
        for code in STYLES
    ]
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _levels_kb(levels: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=v["label"], callback_data=f"cfsm:lvl:{k}")]
        for k, v in levels.items()
    ]
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _exclude_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="cfsm:skipx")],
        _cancel_row(),
    ])


def _scenes_kb() -> InlineKeyboardMarkup:
    items = list(SCENES.items())
    rows = []
    for i in range(0, len(items), 2):
        rows.append([
            InlineKeyboardButton(text=v["label"], callback_data=f"cfsm:scene:{k}")
            for k, v in items[i:i + 2]
        ])
    rows.append([InlineKeyboardButton(text="✍️ Свой вариант", callback_data="cfsm:scene:custom")])
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _captions_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=v["label"], callback_data=f"cfsm:cap:{k}")]
        for k, v in CAPTION_GENRES.items()
    ]
    rows.append(_cancel_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _topic_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="cfsm:skipt")],
        _cancel_row(),
    ])


def _result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Собрать другой запрос", callback_data="cfsm:start")],
    ])


async def _show(target, text: str, kb=None) -> None:
    """Показывает шаг: правит то же сообщение, чтобы не засорять чат."""
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
            await target.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


async def _lost(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _show(callback, TEXT_RESTART + TEXT_MODE, _modes_kb())


# ---------- Сборка запроса ----------
def _is_plain(data: dict) -> bool:
    key = data.get("scene")
    if key == "custom":
        return not (data.get("scene_text") or "").strip()
    scene = SCENES.get(key)
    return not scene or not scene["text"]


def _scene_sentence(data: dict) -> str:
    if _is_plain(data):
        return PLAIN_SENTENCE
    if data.get("scene") == "custom":
        return f"Scene: {data['scene_text'].strip()}."
    return f"Scene: {SCENES[data['scene']]['text']}."


def build_prompt(data: dict) -> str:
    mode = data.get("mode", "caricature")
    technique = style_technique_prompt(data.get("style"))
    level = data.get("level")

    if mode == "portrait":
        level_data = PORTRAIT_LEVELS.get(level) or PORTRAIT_LEVELS["asphoto"]
        keep = KEEP_PLAIN if _is_plain(data) else KEEP_SCENE
        head = (
            "Using the attached photo as the only reference, draw a portrait "
            f"of this person in this style: {technique}."
        )
        body = level_data["text"].format(keep=keep)
        caption = ""
    else:
        level_data = CARICATURE_LEVELS.get(level) or CARICATURE_LEVELS["soft"]
        head = (
            "Using the attached photo as the only reference, draw a caricature "
            f"of this person in this style: {technique}."
        )
        body = level_data["text"]
        exclude = (data.get("exclude") or "").strip()
        if exclude:
            body += f" Do not exaggerate: {exclude}."
        caption = caption_request(data.get("caption"), level, data.get("topic"))

    parts = [head, body, _scene_sentence(data)]
    if caption:
        parts.append(caption)
    parts.append(RULES)
    return " ".join(parts)


def _how_to_text(mode: str | None) -> str:
    fixes = PORTRAIT_FIXES if mode == "portrait" else CARICATURE_FIXES
    lines = []
    for label, phrases in fixes:
        codes = " или ".join(f"<code>{html.escape(p, quote=False)}</code>" for p in phrases)
        lines.append(f"• {label}: {codes}")
    return (
        "<b>Что дальше</b>\n"
        "1. Откройте свой ИИ (Gemini, ChatGPT и др.).\n"
        "2. Прикрепите своё фото.\n"
        "3. Вставьте запрос и отправьте.\n\n"
        "Используйте фото только тех, кто согласен.\n\n"
        "<b>Если результат не устроил</b>, отправьте следующим сообщением одну из поправок:\n"
        + "\n".join(lines)
    )


async def _finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if not (data.get("mode") and data.get("style") and data.get("level")):
        await message.answer(TEXT_RESTART + TEXT_MODE, parse_mode="HTML", reply_markup=_modes_kb())
        return

    prompt = build_prompt(data)
    await message.answer(
        "✅ <b>Запрос готов.</b> Нажмите на текст ниже, чтобы скопировать.\n\n"
        f"<code>{html.escape(prompt, quote=False)}</code>",
        parse_mode="HTML",
    )
    await message.answer(
        _how_to_text(data.get("mode")),
        parse_mode="HTML",
        reply_markup=_result_kb(),
    )


async def _after_scene(target, state: FSMContext) -> None:
    """После выбора сцены: шарж идёт к подписи, портрет сразу к результату."""
    data = await state.get_data()
    if data.get("mode") == "caricature":
        await _show(target, TEXT_CAPTION, _captions_kb())
        return
    is_cb = isinstance(target, CallbackQuery)
    msg = target.message if is_cb else target
    await _finish(msg, state)
    if is_cb:
        with suppress(Exception):
            await msg.delete()


# ---------- Обработчики ----------
@router.message(Command("caricature_prompt"))
@router.callback_query(F.data == "cfsm:start")
async def start_flow(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.answer()
        msg = event.message
    else:
        msg = event
    await msg.answer(TEXT_MODE, parse_mode="HTML", reply_markup=_modes_kb())


@router.callback_query(F.data == "cfsm:cancel")
async def cancel_flow(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _show(callback, "Сборка запроса отменена. Меню: /start")


@router.callback_query(F.data.startswith("cfsm:mode:"))
async def pick_mode(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    mode = callback.data.split(":", 2)[2]
    if mode not in MODES:
        return
    await state.clear()
    await state.update_data(mode=mode)
    await _show(callback, _text_style(mode), _styles_kb())


@router.callback_query(F.data.startswith("cfsm:style:"))
async def pick_style(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    code = callback.data.split(":", 2)[2]
    data = await state.get_data()
    mode = data.get("mode")
    if mode not in MODES:
        await _lost(callback, state)
        return
    if code not in STYLES:
        return
    await state.update_data(style=code)
    if mode == "portrait":
        await _show(callback, TEXT_LEVEL_PORTRAIT, _levels_kb(PORTRAIT_LEVELS))
    else:
        await _show(callback, TEXT_LEVEL_CARICATURE, _levels_kb(CARICATURE_LEVELS))


@router.callback_query(F.data.startswith("cfsm:lvl:"))
async def pick_level(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    data = await state.get_data()
    mode = data.get("mode")
    if mode not in MODES or not data.get("style"):
        await _lost(callback, state)
        return
    levels = PORTRAIT_LEVELS if mode == "portrait" else CARICATURE_LEVELS
    if key not in levels:
        return
    await state.update_data(level=key)
    if mode == "caricature":
        await state.set_state(PromptFSM.exclude_text)
        await _show(callback, TEXT_EXCLUDE, _exclude_kb())
    else:
        await _show(callback, _text_scene(mode), _scenes_kb())


@router.callback_query(PromptFSM.exclude_text, F.data == "cfsm:skipx")
async def skip_exclude(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(None)
    await state.update_data(exclude="")
    await _show(callback, _text_scene("caricature"), _scenes_kb())


@router.message(PromptFSM.exclude_text, F.text)
async def typed_exclude(message: Message, state: FSMContext) -> None:
    text = _clean(message.text)
    if text.startswith("/"):
        await state.clear()
        return
    await state.update_data(exclude=text)
    await state.set_state(None)
    await message.answer(_text_scene("caricature"), parse_mode="HTML", reply_markup=_scenes_kb())


@router.callback_query(F.data.startswith("cfsm:scene:"))
async def pick_scene(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    data = await state.get_data()
    if not (data.get("mode") and data.get("style") and data.get("level")):
        await _lost(callback, state)
        return
    if key == "custom":
        await state.set_state(PromptFSM.scene_text)
        await _show(callback, TEXT_ASK_SCENE, InlineKeyboardMarkup(inline_keyboard=[_cancel_row()]))
        return
    if key not in SCENES:
        return
    await state.update_data(scene=key)
    await _after_scene(callback, state)


@router.message(PromptFSM.scene_text, F.text)
async def typed_scene(message: Message, state: FSMContext) -> None:
    text = _clean(message.text)
    if text.startswith("/"):
        await state.clear()
        return
    await state.update_data(scene="custom", scene_text=text)
    await state.set_state(None)
    await _after_scene(message, state)


@router.callback_query(F.data.startswith("cfsm:cap:"))
async def pick_caption(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    data = await state.get_data()
    if not (data.get("mode") and data.get("style") and data.get("level")):
        await _lost(callback, state)
        return
    if key not in CAPTION_GENRES:
        return
    await state.update_data(caption=key)
    if key == "none":
        await _finish(callback.message, state)
        with suppress(Exception):
            await callback.message.delete()
        return
    await state.set_state(PromptFSM.caption_topic)
    await _show(callback, TEXT_TOPIC, _topic_kb())


@router.callback_query(PromptFSM.caption_topic, F.data == "cfsm:skipt")
async def skip_topic(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(None)
    await state.update_data(topic="")
    await _finish(callback.message, state)
    with suppress(Exception):
        await callback.message.delete()


@router.message(PromptFSM.caption_topic, F.text)
async def typed_topic(message: Message, state: FSMContext) -> None:
    text = _clean(message.text)
    if text.startswith("/"):
        await state.clear()
        return
    await state.update_data(topic=text)
    await state.set_state(None)
    await _finish(message, state)


@router.callback_query(F.data.startswith("cfsm:"))
async def stale_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка из старого сообщения: начинаем заново."""
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "Меню обновилось, начнём заново.\n\n" + TEXT_MODE,
        parse_mode="HTML",
        reply_markup=_modes_kb(),
    )