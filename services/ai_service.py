import io
import json
import base64
import asyncio
import logging
import aiohttp
from PIL import Image
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, CF_ACCOUNT_ID, CF_API_TOKEN
from core.characters import CULTURE_PROMPTS, CHARACTER_PROMPTS, MOOD_PROMPTS

logger = logging.getLogger(__name__)
client = genai.Client(api_key=GEMINI_API_KEY)

BASE_STYLE_PROMPT = (
    "flattering stylish editorial gouache and watercolor cartoon illustration, "
    "smooth youthful glowing skin, NO harsh ink lines on the face, NO wrinkles, NO aging lines, "
    "bright sparkling eyes, charming modern magazine illustration style, "
    "expressive playful pose and witty props, clean colorful brushstrokes on warm paper, no signature, no text"
)

def _build_cf_url(model_path: str) -> str:
    acc = CF_ACCOUNT_ID.strip()
    return f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model_path}"

def _prepare_input_image(raw_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    img.thumbnail((1024, 1024))
    return img

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
        "Content-Type": "application/json"
    }
    payload = {"prompt": prompt, "steps": 6}
    timeout = aiohttp.ClientTimeout(total=25, connect=5)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                logger.warning("CF HTTP %s: %s", resp.status, err_text[:200])
                return None
            parsed = await resp.json()
            if not parsed.get("success"):
                logger.warning("CF API error: %s", str(parsed)[:200])
                return None
            b64_image = parsed.get("result", {}).get("image")
            if not b64_image:
                return None
            raw_png = base64.b64decode(b64_image)
            return await asyncio.to_thread(_compress_output_jpeg, raw_png)

async def generate_happiness_card(
    lang: str,
    character_code: str,
    mood_code: str,
    user_photo_bytes: bytes | None = None
) -> tuple[str, bytes | None]:
    culture_desc = CULTURE_PROMPTS.get(lang, CULTURE_PROMPTS["ru"])
    char_desc = CHARACTER_PROMPTS.get(character_code, CHARACTER_PROMPTS["girl"])
    mood_desc = MOOD_PROMPTS.get(mood_code, MOOD_PROMPTS["warm"])

    if user_photo_bytes:
        photo_rule = (
            "Study the attached photo carefully and create a FLATTERING, YOUTHFUL description of the person "
            "(make them look 5-10 years younger, fresh, radiant, smooth skin without wrinkles, keeping their exact hairstyle, "
            "hair color, eye color, glasses, smile, and clothing style) so the illustration looks like a charming magazine portrait."
        )
    else:
        photo_rule = f"STRICT CHARACTER APPEARANCE (Keep every detail, youthful and flattering): {char_desc}"

    system_instruction = f"""
    You are the creative engine of the 'Happiness Generator' caricature bot.
    {culture_desc}
    {mood_desc}
    {photo_rule}

    Return strictly a JSON object with two keys:
1. "caption": A short, punchy, memorable message (2-3 sentences) in the user's language ({lang}). Blend the selected mood/satire with light PG-13 flirtation, irony, or a witty twist on a famous quote.
2. "image_scene": A vivid editorial cartoon scene in English (max 25 words). Keep the exact character appearance intact, adding witty facial mimicry and props matching the caption.
    """

    contents = ["Generate the JSON response now."]
    if user_photo_bytes:
        pil_img = await asyncio.to_thread(_prepare_input_image, user_photo_bytes)
        contents.insert(0, pil_img)

    logger.info("1. Генерирую текст и сценарий шаржа через Gemini...")
    raw_json_text = None

    for model_name in ["gemini-3.5-flash-lite", "gemini-3.8-flash"]:
        try:
            text_response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json"
                    )
                ),
                timeout=12.0
            )
            if text_response and text_response.text:
                raw_json_text = text_response.text
                logger.info("   Успешно через %s", model_name)
                break
        except Exception as e:
            logger.warning("   %s занята: %s", model_name, e)

    if not raw_json_text:
        raise RuntimeError("Текстовые модели временно недоступны")

    clean_json = raw_json_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(clean_json)
    caption = data.get("caption", "✨ Улыбнись этому дню!")
    image_scene = data.get("image_scene", "")
    logger.info("2. Сцена шаржа: %s", image_scene)

    if user_photo_bytes:
        full_prompt = f"{BASE_STYLE_PROMPT}, recognizable flattering caricature portrait: {image_scene}"
    else:
        full_prompt = f"{BASE_STYLE_PROMPT}, {char_desc} Action & Mood: {image_scene}"

    image_bytes = None
    logger.info("3. Рисую шарж через Cloudflare FLUX...")
    try:
        image_bytes = await _generate_cf_text2img(full_prompt)
        if image_bytes:
            logger.info("   Шарж успешно получен (%d байт)!", len(image_bytes))
    except Exception as e:
        logger.warning("   Ошибка Cloudflare FLUX: %s", e)

    return caption, image_bytes
