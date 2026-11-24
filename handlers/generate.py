import io
import random
import asyncio
import logging
from contextlib import suppress
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from database.models import get_or_create_user, can_generate, increment_usage
from services.ai_service import generate_happiness_card
from core.locales import LOCALES
from handlers.start import get_main_keyboard

logger = logging.getLogger(__name__)
router = Router()

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
async def handle_photo_caricature(message: Message, bot: Bot):
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    lang = user["language"]

    allowed, _ = await can_generate(user["user_id"])
    if not allowed:
        await message.answer(LOCALES[lang]["limit_reached"])
        return

    status_msg = await message.answer(LOCALES[lang]["photo_received"])
    mood_code = random.choice(["warm", "wisdom", "flattery", "greed"])

    try:
        photo_file = await asyncio.wait_for(bot.get_file(message.photo[-1].file_id), timeout=15.0)
        buf = io.BytesIO()
        await asyncio.wait_for(bot.download_file(photo_file.file_path, buf), timeout=20.0)

        caption, img_bytes = await asyncio.wait_for(
            generate_happiness_card(lang, "custom_photo", mood_code, buf.getvalue()),
            timeout=100.0
        )
        if img_bytes:
            out_photo = BufferedInputFile(img_bytes, filename="photo_caricature.jpg")
            sent = await message.answer_photo(photo=out_photo, caption=caption, reply_markup=get_main_keyboard(lang))
            await increment_usage(user["user_id"], "custom_photo", mood_code, True, sent.photo[-1].file_id)
        else:
            await message.answer(caption, reply_markup=get_main_keyboard(lang))
    except asyncio.TimeoutError:
        logger.error("Timeout during photo generation for user %s", user["user_id"])
        await message.answer("⏳ Обработка фото заняла слишком много времени. Попробуй отправить его ещё раз!", reply_markup=get_main_keyboard(lang))
    except Exception as e:
        logger.exception("Photo generation error: %s", e)
        await message.answer("⏳ Сервер перегружен, попробуй отправить фото ещё раз через пару секунд!", reply_markup=get_main_keyboard(lang))
    finally:
        with suppress(Exception):
            await status_msg.delete()
