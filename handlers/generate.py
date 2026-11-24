import io
import asyncio
import logging
from contextlib import suppress
from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from database.models import get_or_create_user, can_generate, increment_usage
from services.ai_service import generate_happiness_card, QuotaExceeded
from core.locales import LOCALES
from handlers.start import get_main_keyboard, PROMPT_BTN

logger = logging.getLogger(__name__)
router = Router()

# Фото, которое человек прислал и ждёт выбора настроения: {user_id: file_id}
PENDING_PHOTOS: dict[int, str] = {}
# Кто сейчас рисуется, чтобы двойное нажатие не тратило лимит
BUSY_USERS: set[int] = set()

MOODS = ["warm", "wisdom", "greed", "flattery", "lust"]

ASK_MOOD = {
    "ru": "📸 Фото получено! Выберите настроение шаржа:",
    "uk": "📸 Фото отримано! Оберіть настрій шаржу:",
    "en": "📸 Photo received! Pick the mood of your caricature:",
    "es": "📸 ¡Foto recibida! Elige el ánimo de tu caricatura:",
}

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

QUOTA_TEXT = {
    "ru": "🎨 Бесплатные картинки на сегодня закончились. Они обновятся ночью, приходите завтра! Ваш лимит не потрачен.",
    "uk": "🎨 Безкоштовні картинки на сьогодні закінчилися. Вони оновляться вночі, приходьте завтра! Ваш ліміт не витрачено.",
    "en": "🎨 Today's free drawings are used up. They refresh overnight, come back tomorrow! Your limit was not spent.",
    "es": "🎨 Los dibujos gratuitos de hoy se agotaron. Se renuevan por la noche, ¡vuelve mañana! Tu límite no se gastó.",
}

# Подсказка про сборку промпта (только для языков, где она есть)
QUOTA_HINT = {
    "ru": "\n\n🎁 А пока можно собрать промпт и нарисовать шарж в своём ИИ: кнопка ниже.",
    "uk": "\n\n🎁 А поки можна зібрати промпт і намалювати шарж у своєму ШІ: кнопка нижче.",
}


def _quota_message(lang: str) -> str:
    return QUOTA_TEXT.get(lang, QUOTA_TEXT["ru"]) + QUOTA_HINT.get(lang, "")


def get_photo_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = LOCALES[lang]
    rows = [
        [InlineKeyboardButton(text=t["btn_warm"], callback_data="pmood:warm"),
         InlineKeyboardButton(text=t["btn_wisdom"], callback_data="pmood:wisdom")],
        [InlineKeyboardButton(text=t["btn_greed"], callback_data="pmood:greed"),
         InlineKeyboardButton(text=t["btn_flattery"], callback_data="pmood:flattery")],
        [InlineKeyboardButton(text=t["btn_lust"], callback_data="pmood:lust")],
        [InlineKeyboardButton(text=t["btn_char"], callback_data="menu:chars"),
         InlineKeyboardButton(text=t["btn_lang"], callback_data="menu:langs")],
    ]
    if lang in PROMPT_BTN:
        rows.append([InlineKeyboardButton(text=PROMPT_BTN[lang], callback_data="cfsm:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("mood:"))
async def handle_mood_generate(callback: CallbackQuery):
    mood_code = callback.data.split(":")[1]
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    lang = user["language"]

    allowed, _ = await can_generate(user["user_id"])
    if not allowed:
        await callback.answer(LOCALES[lang]["limit_reached"], show_alert=True)
        return

    await callback.answer()
    status_msg = await callback.message.answer(LOCALES[lang]["generating"])

    try:
        caption, img_bytes = await asyncio.wait_for(
            generate_happiness_card(lang, user["character_code"], mood_code),
            timeout=40.0
        )
        if img_bytes:
            photo = BufferedInputFile(img_bytes, filename="caricature.jpg")
            sent = await callback.message.answer_photo(photo=photo, caption=caption, reply_markup=get_main_keyboard(lang))
            await increment_usage(user["user_id"], user["character_code"], mood_code, False, sent.photo[-1].file_id)
        else:
            await callback.message.answer(
                f"{caption}\n\n(🎨 Художник сегодня в отпуске — картинка не сгенерировалась)",
                reply_markup=get_main_keyboard(lang)
            )
            await increment_usage(user["user_id"], user["character_code"], mood_code, False, "")
    except QuotaExceeded:
        await callback.message.answer(
            _quota_message(lang),
            reply_markup=get_main_keyboard(lang),
        )
    except asyncio.TimeoutError:
        logger.error("Timeout during mood generation for user %s", user["user_id"])
        await callback.message.answer("⏳ Генерация заняла слишком много времени. Нажми на кнопку ещё раз!", reply_markup=get_main_keyboard(lang))
    except Exception as e:
        logger.exception("Generation error: %s", e)
        await callback.message.answer("⏳ Сервер вдохновения перегружен. Нажми на кнопку ещё раз через пару секунд!", reply_markup=get_main_keyboard(lang))
    finally:
        with suppress(Exception):
            await status_msg.delete()


@router.message(F.photo)
async def handle_photo_received(message: Message):
    """Фото пришло: запоминаем и спрашиваем настроение кнопками."""
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    lang = user["language"]

    allowed, _ = await can_generate(user["user_id"])
    if not allowed:
        await message.answer(LOCALES[lang]["limit_reached"])
        return

    if len(PENDING_PHOTOS) > 500:
        PENDING_PHOTOS.clear()
    PENDING_PHOTOS[user["user_id"]] = message.photo[-1].file_id

    await message.answer(
        ASK_MOOD.get(lang, ASK_MOOD["ru"]),
        reply_markup=get_photo_keyboard(lang),
    )


@router.callback_query(F.data.startswith("pmood:"))
async def handle_photo_mood(callback: CallbackQuery):
    """Настроение выбрано: рисуем шарж по запомненному фото."""
    mood_code = callback.data.split(":", 1)[1]
    if mood_code not in MOODS:
        await callback.answer()
        return

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
    status_msg = await callback.message.answer(LOCALES[lang]["photo_received"])

    try:
        bot: Bot = callback.bot
        photo_file = await asyncio.wait_for(bot.get_file(file_id), timeout=15.0)
        buf = io.BytesIO()
        await asyncio.wait_for(bot.download_file(photo_file.file_path, buf), timeout=20.0)

        caption, img_bytes = await asyncio.wait_for(
            generate_happiness_card(lang, "custom_photo", mood_code, buf.getvalue()),
            timeout=100.0
        )
        if img_bytes:
            out_photo = BufferedInputFile(img_bytes, filename="photo_caricature.jpg")
            sent = await callback.message.answer_photo(
                photo=out_photo,
                caption=caption,
                reply_markup=get_photo_keyboard(lang),
            )
            await increment_usage(user_id, "custom_photo", mood_code, True, sent.photo[-1].file_id)
        else:
            await callback.message.answer(
                f"{caption}\n\n(🎨 Картинка не получилась. Выберите настроение ещё раз)",
                reply_markup=get_photo_keyboard(lang),
            )
    except QuotaExceeded:
        await callback.message.answer(
            _quota_message(lang),
            reply_markup=get_photo_keyboard(lang),
        )
    except asyncio.TimeoutError:
        logger.error("Timeout during photo generation for user %s", user_id)
        await callback.message.answer(
            "⏳ Рисование заняло слишком много времени. Нажмите кнопку ещё раз!",
            reply_markup=get_photo_keyboard(lang),
        )
    except Exception as e:
        logger.exception("Photo generation error: %s", e)
        await callback.message.answer(
            "⏳ Сервер перегружен, нажмите кнопку ещё раз через пару секунд!",
            reply_markup=get_photo_keyboard(lang),
        )
    finally:
        BUSY_USERS.discard(user_id)
        with suppress(Exception):
            await status_msg.delete()