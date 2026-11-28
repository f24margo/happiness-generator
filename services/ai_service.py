import asyncio
import base64
import io
import json
import logging
from datetime import datetime, timezone
import aiohttp
from google import genai
from google.genai import types
from PIL import Image, ImageOps
from config import CF_ACCOUNT_ID, CF_API_TOKEN, GEMINI_API_KEY
from core.characters import CHARACTER_PROMPTS, CULTURE_PROMPTS, MOOD_PROMPTS
from core.styles import style_photo_prompt, style_hero_prompt
from core.captions import CAPTION_GENRES, CAPTION_TONES
from handlers.caricature_prompt import build_prompt

logger = logging.getLogger(__name__)
client = genai.Client(api_key=GEMINI_API_KEY)

GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]

# Настройки рисования по умолчанию: шарж, мягкий гротеск, простой фон, без подписи
DEFAULT_SETTINGS = {
    "mode": "caricature",
    "style": "gouache",
    "level": "soft",
    "scene": "plain",
    "exclude": "",
    "caption": "none",
    "topic": "",
}

LANG_NAMES = {"ru": "Russian", "uk": "Ukrainian", "en": "English", "es": "Spanish"}

FALLBACK_SCENES = {
    "warm": "a friendly confident smile, a cup of coffee in hand, soft golden light",
    "wisdom": "a thoughtful half-smile, an open book in hand, a cozy study with bookshelves",
    "greed": "hugging a giant piggy bank and a heap of gold coins with a sly smirk",
    "flattery": "an over-the-top sweet smile, holding a golden crown, one hand behind the back with fingers crossed",
    "lust": "a candle-lit dinner table, a single rose in hand, a charming wink",
}

FALLBACK_CAPTIONS = {
    "ru": "Улыбка — самый дешёвый способ выглядеть лучше. А вам она к лицу!",
    "uk": "Усмішка — найдешевший спосіб виглядати краще. А вам вона личить!",
    "en": "A smile is the cheapest way to look better. And it suits you!",
    "es": "Una sonrisa es la forma más barata de verte mejor. ¡Y a ti te sienta de maravilla!",
}


class QuotaExceeded(Exception):
    """Бесплатная суточная норма Cloudflare закончилась."""


_quota_day: str | None = None


def _today_utc() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:") + str(now.minute // 30)


def _quota_exhausted_today() -> bool:
    return _quota_day == _today_utc()


def _raise_if_quota(status: int, text: str) -> None:
    global _quota_day
    low = text.lower()
    if status == 429 or "neurons" in low or "allocation" in low or "4006" in low:
        _quota_day = _today_utc()
        logger.warning("Cloudflare: суточная норма исчерпана (HTTP %s)", status)
        raise QuotaExceeded()


BASE_STYLE_PROMPT = (
    "flattering stylish editorial gouache and watercolor cartoon illustration, "
    "smooth youthful glowing skin, NO harsh ink lines on the face, NO wrinkles, NO aging lines, "
    "bright sparkling eyes, charming modern magazine illustration style, "
    "expressive playful pose and witty props, clean colorful brushstrokes on warm paper, no signature, no text"
)

CARICATURE_PROMPT_SYSTEM_INSTRUCTION = """You are a prompt engineer for image generation and editing in Gemini.
The user will attach their own photo directly inside Gemini and paste your English prompt.
Transform three user inputs into one clear, effective English prompt that preserves facial likeness and identity from the attached photo while applying a caricature style.

Rules:
1. Explicitly instruct Gemini to use the attached photo as the primary identity and facial likeness reference, preserving key facial features, hair, glasses/beard if present, and likeness details specified by the user.
2. Apply the requested caricature exaggeration, expression/emotion, art style, scene, lighting, and mood naturally without replacing the person with an unrelated stranger.
3. Keep prompt_en concise, concrete, and ready to copy-paste (1-2 clear sentences/clauses, no markdown code fences).
4. Write summary_ru in Russian (1-2 short sentences) summarizing what likeness anchors, caricature style/emotion, and scene/mood were combined.
5. Return strictly valid JSON with keys "prompt_en" and "summary_ru".
"""


def _build_cf_url(model_path: str) -> str:
    acc = CF_ACCOUNT_ID.strip()
    return f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model_path}"


def _prepare_input_image(raw_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1024, 1024))
    return img


def _prepare_cf_reference(raw_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((512, 512))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _compress_output_jpeg(raw_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


async def _generate_cf_text2img(prompt: str) -> bytes | None:
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        return None
    url = _build_cf_url("@cf/black-forest-labs/flux-1-schnell")
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN.strip()}",
        "Content-Type": "application/json",
    }
    payload = {"prompt": prompt, "steps": 4}
    timeout = aiohttp.ClientTimeout(total=25, connect=5)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                logger.warning("CF HTTP %s: %s", resp.status, err_text[:200])
                _raise_if_quota(resp.status, err_text)
                return None
            parsed = await resp.json()
            if not parsed.get("success"):
                logger.warning("CF API error: %s", str(parsed)[:200])
                _raise_if_quota(200, str(parsed))
                return None
            b64_image = parsed.get("result", {}).get("image")
            if not b64_image:
                return None
            raw_png = base64.b64decode(b64_image)
            return await asyncio.to_thread(_compress_output_jpeg, raw_png)


async def _generate_cf_with_reference(prompt: str, ref_png: bytes) -> bytes | None:
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        return None
    url = _build_cf_url("@cf/black-forest-labs/flux-2-klein-4b")
    headers = {"Authorization": f"Bearer {CF_API_TOKEN.strip()}"}
    form = aiohttp.FormData()
    form.add_field("prompt", prompt)
    form.add_field("width", "768")
    form.add_field("height", "1024")
    form.add_field(
        "input_image_0", ref_png, filename="face.png", content_type="image/png"
    )
    timeout = aiohttp.ClientTimeout(total=60, connect=5)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, data=form) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                logger.warning("CF ref HTTP %s: %s", resp.status, err_text[:300])
                _raise_if_quota(resp.status, err_text)
                return None
            parsed = await resp.json()
            b64_image = (parsed.get("result") or {}).get("image")
            if not b64_image:
                logger.warning("CF ref: нет картинки в ответе: %s", str(parsed)[:300])
                _raise_if_quota(200, str(parsed))
                return None
            raw_png = base64.b64decode(b64_image)
            return await asyncio.to_thread(_compress_output_jpeg, raw_png)


async def _ask_gemini(contents: list, system_instruction: str) -> str | None:
    """Спрашивает Gemini: две модели, по две попытки каждая."""
    for model_name in GEMINI_MODELS:
        for attempt in (1, 2):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json",
                        ),
                    ),
                    timeout=9.0,
                )
                if response and response.text:
                    logger.info("   Успешно через %s", model_name)
                    return response.text
            except Exception as e:
                logger.warning("   %s (попытка %d) не ответила: %s", model_name, attempt, e)
                if attempt == 1:
                    await asyncio.sleep(1.5)
    return None


async def build_caricature_prompt(
    likeness_details: str,
    style_emotion: str,
    scene_mood: str,
    lang: str = "ru",
) -> tuple[str, str]:
    user_payload = (
        f"User language: {lang}\n"
        f"Likeness & details to preserve/add: {likeness_details.strip()}\n"
        f"Caricature style & emotion: {style_emotion.strip()}\n"
        f"Scene & mood: {scene_mood.strip()}"
    )

    for model_name in GEMINI_MODELS:
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=user_payload,
                    config=types.GenerateContentConfig(
                        system_instruction=CARICATURE_PROMPT_SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        temperature=0.6,
                    ),
                ),
                timeout=12.0,
            )
            raw_text = (response.text or "").strip()
            clean_json = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(clean_json)
            prompt_en = str(data.get("prompt_en", "")).strip()
            summary_ru = str(data.get("summary_ru", "")).strip()
            if prompt_en and summary_ru:
                return prompt_en, summary_ru
        except Exception as e:
            logger.warning("build_caricature_prompt через %s не удался: %s", model_name, e)

    fallback_prompt = (
        f"Using the attached photo as the primary identity reference, create a caricature "
        f"({style_emotion.strip()}) while preserving facial likeness and details ({likeness_details.strip()}). "
        f"Set the scene in {scene_mood.strip()}, expressive proportions, clean composition, no text or watermarks."
    )
    fallback_summary = (
        f"Опора на фото ({likeness_details.strip()}), шарж и эмоция ({style_emotion.strip()}), "
        f"сцена и настроение ({scene_mood.strip()})."
    )
    return fallback_prompt, fallback_summary


async def generate_happiness_card(
    lang: str,
    character_code: str,
    mood_code: str,
    user_photo_bytes: bytes | None = None,
    style_code: str = "gouache",
) -> tuple[str, bytes | None]:
    # Норма Cloudflare ещё закрыта: не тратим время и Gemini
    if _quota_exhausted_today():
        raise QuotaExceeded()

    culture_desc = CULTURE_PROMPTS.get(lang, CULTURE_PROMPTS["ru"])
    char_desc = CHARACTER_PROMPTS.get(character_code, CHARACTER_PROMPTS["girl"])
    mood_desc = MOOD_PROMPTS.get(mood_code, MOOD_PROMPTS["warm"])

    if user_photo_bytes:
        photo_rule = (
            "A photo of the person is attached. The image generator receives the same photo as a "
            "reference, so DO NOT describe the person's face, age or skin. Use the photo only to "
            "understand who the person is, their mood and what props or scene would suit them."
        )
        scene_rule = (
            "A vivid editorial cartoon scene in English (max 25 words): pose, facial expression, "
            "props and setting that match the caption. Do NOT describe facial features, age or skin."
        )
    else:
        photo_rule = f"STRICT CHARACTER APPEARANCE (Keep every detail, youthful and flattering): {char_desc}"
        scene_rule = (
            "A vivid editorial cartoon scene in English (max 25 words). Keep the exact character "
            "appearance intact, adding witty facial mimicry and props matching the caption."
        )

    system_instruction = f"""
    You are the creative engine of the 'Happiness Generator' caricature bot.
    {culture_desc}
    {mood_desc}
    {photo_rule}

    Return strictly a JSON object with two keys:
1. "caption": A short, punchy, memorable message (2-3 sentences) in the user's language ({lang}). Blend the selected mood/satire with light PG-13 flirtation, irony, or a witty twist on a famous quote.
2. "image_scene": {scene_rule}
    """

    contents = ["Generate the JSON response now."]
    if user_photo_bytes:
        pil_img = await asyncio.to_thread(_prepare_input_image, user_photo_bytes)
        contents.insert(0, pil_img)

    logger.info("1. Генерирую текст и сценарий шаржа через Gemini...")
    raw_json_text = await _ask_gemini(contents, system_instruction)

    # Запасные значения на случай, если Gemini недоступен
    caption = FALLBACK_CAPTIONS.get(lang, FALLBACK_CAPTIONS["ru"])
    image_scene = FALLBACK_SCENES.get(mood_code, FALLBACK_SCENES["warm"])

    if raw_json_text:
        try:
            clean_json = raw_json_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(clean_json)
            caption = data.get("caption") or caption
            image_scene = data.get("image_scene") or image_scene
        except Exception as e:
            logger.warning("   Не удалось разобрать ответ Gemini, берём запасной текст: %s", e)
    else:
        logger.warning("   Gemini недоступен, берём запасную подпись и сцену")

    logger.info("2. Сцена шаржа: %s", image_scene)

    hero_style = style_hero_prompt(style_code, BASE_STYLE_PROMPT)

    if user_photo_bytes:
        full_prompt = (
            f"Draw a caricature of the person in image 0 in this style: {style_photo_prompt(style_code)}. "
            "Render the whole picture, including the scene, strictly in this style. "
            "Keep the identity clearly recognizable: same face and same hairstyle. "
            "Draw only what is visible in the photo. "
            "If the person wears no glasses, draw no glasses. "
            "Add no accessories that are not in the photo. "
            "Keep the real eye shape, nose shape and skin tone from the photo; "
            "exaggerate only the head size and one distinctive feature slightly. "
            "Keep wrinkles and age as in the photo. "
            f"Scene: {image_scene}. "
            "Do not reuse the background of the photo. "
            "Never put any text, letters or signs in the picture. "
            "Head and shoulders, full head visible with margin around."
        )
    else:
        full_prompt = f"{hero_style}, {char_desc} Action & Mood: {image_scene}"

    logger.info("   Стиль: %s. Запрос к FLUX: %s", style_code, full_prompt[:500])

    image_bytes = None
    logger.info("3. Рисую шарж через Cloudflare FLUX...")
    try:
        if user_photo_bytes:
            ref = await asyncio.to_thread(_prepare_cf_reference, user_photo_bytes)
            image_bytes = await _generate_cf_with_reference(full_prompt, ref)
        if not image_bytes:
            fallback = f"{hero_style}, recognizable caricature portrait: {image_scene}"
            image_bytes = await _generate_cf_text2img(fallback)
        if image_bytes:
            logger.info("   Шарж успешно получен (%d байт)!", len(image_bytes))
    except QuotaExceeded:
        raise
    except Exception as e:
        logger.warning("   Ошибка Cloudflare FLUX: %s", e)

    return caption, image_bytes


# =====================================================================
# Рисование по настройкам (режим, стиль, сила, сцена, подпись)
# =====================================================================

def _flux_prompt(settings: dict) -> str:
    """Запрос к рисующей модели: тот же текст, что в «Промпте для своего ИИ»,
    но без подписи, и фото названо «image 0»."""
    base = build_prompt({**settings, "caption": "none"})
    base = base.replace("the attached photo", "image 0")
    return base + " Do not reuse the background of the photo. Full head visible with margin around."


async def _make_caption(lang: str, settings: dict, photo_bytes: bytes) -> str:
    """Подпись выбранного жанра через Gemini. Если Gemini занят, берётся запасная."""
    fallback = FALLBACK_CAPTIONS.get(lang, FALLBACK_CAPTIONS["ru"])
    genre = CAPTION_GENRES.get(settings.get("caption"))
    if not genre or not genre["text"]:
        return ""

    tone = CAPTION_TONES.get(settings.get("level"), CAPTION_TONES["soft"])
    topic = (settings.get("topic") or "").strip()
    topic_line = f"Topic, occasion or name to use: {topic}.\n" if topic else ""
    system_instruction = (
        "You write short captions for a friendly caricature bot.\n"
        f"Write in {LANG_NAMES.get(lang, 'Russian')}.\n"
        f"Genre: {genre['text']}.\n"
        f"{tone}\n"
        f"{topic_line}"
        "A photo of the person is attached: you may mention one harmless visible detail "
        "(clothes, glasses, props), never their age, weight or looks.\n"
        "Never attribute the text to a real person. No hashtags and no emojis.\n"
        'Return strictly a JSON object: {"caption": "..."}'
    )

    try:
        pil_img = await asyncio.to_thread(_prepare_input_image, photo_bytes)
        raw = await _ask_gemini([pil_img, "Write the caption now."], system_instruction)
        if not raw:
            logger.warning("   Gemini недоступен, берём запасную подпись")
            return fallback
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        text = str(json.loads(clean).get("caption", "")).strip()
        return text[:900] if text else fallback
    except Exception as e:
        logger.warning("   Не удалось получить подпись: %s", e)
        return fallback


async def generate_by_settings(
    lang: str,
    photo_bytes: bytes,
    settings: dict | None = None,
) -> tuple[str, bytes | None]:
    """Рисует по фото и настройкам. Возвращает (подпись или "", картинка или None)."""
    if _quota_exhausted_today():
        raise QuotaExceeded()

    s = {**DEFAULT_SETTINGS, **(settings or {})}
    if s.get("mode") == "portrait":
        s["caption"] = "none"

    prompt = _flux_prompt(s)
    logger.info(
        "Рисую по настройкам %s. Запрос к FLUX: %s",
        {k: s.get(k) for k in ("mode", "style", "level", "scene", "caption")},
        prompt[:500],
    )

    caption_task = None
    if s.get("caption") != "none":
        caption_task = asyncio.create_task(_make_caption(lang, s, photo_bytes))

    image_bytes = None
    try:
        ref = await asyncio.to_thread(_prepare_cf_reference, photo_bytes)
        image_bytes = await _generate_cf_with_reference(prompt, ref)
        if image_bytes:
            logger.info("   Картинка получена (%d байт)", len(image_bytes))
    except QuotaExceeded:
        if caption_task:
            caption_task.cancel()
        raise
    except Exception as e:
        logger.warning("   Ошибка Cloudflare FLUX: %s", e)

    caption = ""
    if caption_task:
        try:
            caption = await caption_task
        except Exception:
            caption = FALLBACK_CAPTIONS.get(lang, FALLBACK_CAPTIONS["ru"])

    return caption, image_bytes