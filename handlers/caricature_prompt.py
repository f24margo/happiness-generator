from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from services.ai_service import build_caricature_prompt

router = Router()


class CaricaturePromptFSM(StatesGroup):
    likeness_details = State()
    style_emotion = State()
    scene_mood = State()


LIKENESS_PRESETS: dict[str, str] = {
    "face_hair": "строго сохранить черты лица, пропорции и причёску с прикреплённого фото",
    "beard_glasses": "сохранить форму лица, бороду/усы или очки и живую мимику с фото",
    "with_prop": "сохранить узнаваемость с фото и добавить в руку кружку кофе или гаджет",
}

STYLE_PRESETS: dict[str, str] = {
    "friendly_smirk": "дружеский шарж с лёгким гротеском и хитрой улыбкой",
    "fig_3d": "стиль 3D-фигурки с выразительной мимикой и эмоцией восторга",
    "comic_wink": "яркий шарж в стиле современной иллюстрации/комикса с прищуром",
}

SCENE_PRESETS: dict[str, str] = {
    "desk_warm": "за рабочим столом с ноутбуком, тёплый уютный свет и лёгкий юмор",
    "cozy_chill": "в уютной домашней обстановке с чашкой чая, спокойное доброе настроение",
    "dynamic_pop": "на ярком выразительном фоне с динамичным освещением и драйвом",
}


def _step1_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Черты лица и причёска с фото", callback_data="cfsm:s1:face_hair")],
            [InlineKeyboardButton(text="👓 Борода / очки и мимика с фото", callback_data="cfsm:s1:beard_glasses")],
            [InlineKeyboardButton(text="☕ Сходство с фото + кружка/деталь", callback_data="cfsm:s1:with_prop")],
            [InlineKeyboardButton(text="✖ Отмена", callback_data="cfsm:cancel")],
        ]
    )


def _step2_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="😏 Дружеский шарж + ухмылка", callback_data="cfsm:s2:friendly_smirk")],
            [InlineKeyboardButton(text="🧸 3D-фигурка + эмоция восторга", callback_data="cfsm:s2:fig_3d")],
            [InlineKeyboardButton(text="🎨 Иллюстрация/комикс + прищур", callback_data="cfsm:s2:comic_wink")],
            [InlineKeyboardButton(text="✖ Отмена", callback_data="cfsm:cancel")],
        ]
    )


def _step3_keyboard(selected_scene: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💻 Рабочий стол и тёплый свет", callback_data="cfsm:s3:desk_warm")],
        [InlineKeyboardButton(text="🏡 Уютная обстановка и отдых", callback_data="cfsm:s3:cozy_chill")],
        [InlineKeyboardButton(text="⚡ Яркий фон и драйв", callback_data="cfsm:s3:dynamic_pop")],
    ]
    if selected_scene:
        rows.append([InlineKeyboardButton(text="✨ Собрать промпт", callback_data="cfsm:build")])
    rows.append([InlineKeyboardButton(text="✖ Отмена", callback_data="cfsm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Собрать новый промпт", callback_data="cfsm:start")],
        ]
    )


async def _send_step1(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CaricaturePromptFSM.likeness_details)
    text = (
        "Шаг 1 из 3. **Что сохранить для сходства с фото и что добавить?**\n"
        "Фото вы прикрепите уже у себя в Gemini. Нажмите кнопку ниже или напишите свой вариант."
    )
    if isinstance(target, CallbackQuery):
        await target.message.answer(text, parse_mode="Markdown", reply_markup=_step1_keyboard())
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=_step1_keyboard())


async def _send_step2(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CaricaturePromptFSM.style_emotion)
    text = (
        "Шаг 2 из 3. **Какая мимика и стиль шаржа?**\n"
        "Выберите готовый вариант кнопкой или опишите своими словами."
    )
    if isinstance(target, CallbackQuery):
        await target.message.answer(text, parse_mode="Markdown", reply_markup=_step2_keyboard())
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=_step2_keyboard())


async def _send_step3(
    target: Message | CallbackQuery,
    state: FSMContext,
    selected_scene: str | None = None,
) -> None:
    await state.set_state(CaricaturePromptFSM.scene_mood)
    extra = (
        f"\n\nВыбрано: *{selected_scene}*. Нажмите **«✨ Собрать промпт»** или допишите детали текстом."
        if selected_scene
        else ""
    )
    text = (
        "Шаг 3 из 3. **Какая сцена, фон и настроение кадра?**\n"
        f"Выберите вариант кнопкой или напишите свой текст.{extra}"
    )
    if isinstance(target, CallbackQuery):
        await target.message.answer(text, parse_mode="Markdown", reply_markup=_step3_keyboard(selected_scene))
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=_step3_keyboard(selected_scene))


async def _finalize_prompt(message: Message, state: FSMContext, scene_mood: str) -> None:
    data = await state.get_data()
    await state.clear()

    wait_msg = await message.answer("✨ Собираю промпт с опорой на ваше фото...")
    prompt_en, summary_ru = await build_caricature_prompt(
        likeness_details=data.get("likeness_details", ""),
        style_emotion=data.get("style_emotion", ""),
        scene_mood=scene_mood,
    )
    await wait_msg.edit_text(
        "Готовый промпт (вставьте в свой Gemini вместе с прикреплённым фото):\n\n"
        f"`{prompt_en}`\n\n"
        f"Что заложено: {summary_ru}",
        parse_mode="Markdown",
        reply_markup=_result_keyboard(),
    )


@router.message(Command("caricature_prompt"))
@router.callback_query(F.data == "cfsm:start")
async def start_caricature_fsm(event: Message | CallbackQuery, state: FSMContext) -> None:
    await _send_step1(event, state)


@router.callback_query(F.data == "cfsm:cancel")
async def cancel_caricature_fsm(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Сборка промпта отменена.")
    await callback.answer()


@router.callback_query(CaricaturePromptFSM.likeness_details, F.data.startswith("cfsm:s1:"))
async def pick_step1(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.removeprefix("cfsm:s1:")
    value = LIKENESS_PRESETS.get(key)
    if not value:
        await callback.answer("Неизвестный вариант", show_alert=False)
        return
    await state.update_data(likeness_details=value)
    await _send_step2(callback, state)


@router.message(CaricaturePromptFSM.likeness_details, F.text)
async def text_step1(message: Message, state: FSMContext) -> None:
    await state.update_data(likeness_details=message.text.strip())
    await _send_step2(message, state)


@router.callback_query(CaricaturePromptFSM.style_emotion, F.data.startswith("cfsm:s2:"))
async def pick_step2(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.removeprefix("cfsm:s2:")
    value = STYLE_PRESETS.get(key)
    if not value:
        await callback.answer("Неизвестный вариант", show_alert=False)
        return
    await state.update_data(style_emotion=value)
    await _send_step3(callback, state)


@router.message(CaricaturePromptFSM.style_emotion, F.text)
async def text_step2(message: Message, state: FSMContext) -> None:
    await state.update_data(style_emotion=message.text.strip())
    await _send_step3(message, state)


@router.callback_query(CaricaturePromptFSM.scene_mood, F.data.startswith("cfsm:s3:"))
async def pick_step3(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.removeprefix("cfsm:s3:")
    value = SCENE_PRESETS.get(key)
    if not value:
        await callback.answer("Неизвестный вариант", show_alert=False)
        return
    await state.update_data(scene_mood=value)
    await _send_step3(callback, state, selected_scene=value)


@router.callback_query(CaricaturePromptFSM.scene_mood, F.data == "cfsm:build")
async def build_from_preset(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    scene_mood = data.get("scene_mood") or SCENE_PRESETS["desk_warm"]
    await callback.answer()
    await _finalize_prompt(callback.message, state, scene_mood)


@router.message(CaricaturePromptFSM.scene_mood, F.text)
async def text_step3(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    preset = data.get("scene_mood")
    typed = message.text.strip()
    scene_mood = f"{preset}, {typed}" if preset else typed
    await _finalize_prompt(message, state, scene_mood)