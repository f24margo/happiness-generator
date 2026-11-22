import io
import json
import base64
import asyncio
import tempfile
import os
import subprocess
from PIL import Image
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, CF_ACCOUNT_ID, CF_API_TOKEN
from core.characters import CULTURE_PROMPTS, CHARACTER_PROMPTS, MOOD_PROMPTS

client = genai.Client(api_key=GEMINI_API_KEY)

BASE_STYLE_PROMPT = (
    "flattering stylish editorial gouache and watercolor cartoon illustration, "
    "smooth youthful glowing skin, NO harsh ink lines on the face, NO wrinkles, NO aging lines, "
    "bright sparkling eyes, charming modern magazine illustration style, "
    "expressive playful pose and witty props, clean colorful brushstrokes on warm paper, no signature, no text"
)

def _build_cf_url(model_path: str) -> str:
    host = ".".join(["api", "cloudflare", "com"])
    acc = CF_ACCOUNT_ID.strip()
    return f"https://{host}/client/v4/accounts/{acc}/ai/run/{model_path}"

def _generate_cf_text2img_sync(prompt: str) -> bytes | None:
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        return None
    url = _build_cf_url("@cf/black-forest-labs/flux-1-schnell")
    payload = json.dumps({"prompt": prompt, "steps": 6})
    cmd = [
        "curl", "-s", "-X", "POST", url,
        "-H", f"Authorization: Bearer {CF_API_TOKEN.strip()}",
        "-H", "Content-Type: application/json",
        "-d", payload
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if res.returncode != 0:
        print("CURL ERR:", res.returncode, res.stderr)
        return None
    parsed = json.loads(res.stdout)
    if not parsed.get("success"):
        print("CF ERR:", res.stdout[:200])
        return None
    b64_image = parsed.get("result", {}).get("image")
    return base64.b64decode(b64_image) if b64_image else None

def _generate_cf_img2img_sync(prompt: str, photo_bytes: bytes) -> bytes | None:
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        return None

    img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    img.thumbnail((512, 512))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_int_array = list(buf.getvalue())

    url = _build_cf_url("@cf/runwayml/stable-diffusion-v1-5-img2img")
    payload_dict = {
        "prompt": prompt,
        "image": image_int_array,
        "strength": 0.58,
        "guidance": 8.5,
        "num_steps": 20
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(payload_dict, tmp)
        tmp_path = tmp.name

    try:
        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", f"Authorization: Bearer {CF_API_TOKEN.strip()}",
            "-H", "Content-Type: application/json",
            "--data-binary", f"@{tmp_path}"
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=50)
        if res.returncode != 0 or not res.stdout:
            return None
        if res.stdout.startswith(b"\x89PNG") or res.stdout.startswith(b"\xff\xd8"):
            return res.stdout
        print("IMG2IMG RESP:", res.stdout[:200])
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

async def generate_happiness_card(
    lang: str,
    character_code: str,
    mood_code: str,
    user_photo_bytes: bytes | None = None
) -> tuple[str, bytes | None]:
    culture_desc = CULTURE_PROMPTS.get(lang, CULTURE_PROMPTS["ru"])
    char_desc = CHARACTER_PROMPTS.get(character_code, CHARACTER_PROMPTS["girl"])
    mood_desc = MOOD_PROMPTS.get(mood_code, MOOD_PROMPTS["warm"])

    photo_rule = (
        "Study the attached photo carefully and create a FLATTERING, YOUTHFUL description of the person "
        "(make them look 5-10 years younger, fresh, radiant, smooth skin without wrinkles, keeping their exact hairstyle, "
        "hair color, eye color, glasses, smile, and clothing style) so the illustration looks like a charming, flattering magazine portrait."
        if user_photo_bytes else f"STRICT CHARACTER APPEARANCE (Keep every detail, youthful and flattering): {char_desc}"
    )

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
        pil_img = Image.open(io.BytesIO(user_photo_bytes))
        contents.insert(0, pil_img)

    print("1. Генерирую текст и сценарий шаржа через Gemini...")
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
                timeout=10.0
            )
            if text_response and text_response.text:
                raw_json_text = text_response.text
                print(f"   Успешно через {model_name}")
                break
        except Exception as e:
            print(f"   {model_name} занята: {e}")

    if not raw_json_text:
        raise RuntimeError("Текстовые модели временно недоступны")

    clean_json = raw_json_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(clean_json)
    caption = data.get("caption", "✨ Улыбнись этому дню!")
    image_scene = data.get("image_scene", "")
    print(f"2. Сцена шаржа: {image_scene}")

    image_bytes = None
    if user_photo_bytes:
        full_prompt = f"{BASE_STYLE_PROMPT}, recognizable caricature portrait: {image_scene}"
        print("3. Рисую портретный шарж по описанию фото через Cloudflare FLUX...")
        try:
            image_bytes = await asyncio.to_thread(_generate_cf_text2img_sync, full_prompt)
            if image_bytes:
                print("   Портретный шарж по фото успешно получен!")
        except Exception as e:
            print(f"   Ошибка Cloudflare FLUX: {e}")
    else:
        full_prompt = f"{BASE_STYLE_PROMPT}, {char_desc} Action & Mood: {image_scene}"
        print("3. Рисую постоянного героя через Cloudflare FLUX...")
        try:
            image_bytes = await asyncio.to_thread(_generate_cf_text2img_sync, full_prompt)
            if image_bytes:
                print("   Шарж героя успешно получен!")
        except Exception as e:
            print(f"   Ошибка Cloudflare FLUX: {e}")

    return caption, image_bytes
