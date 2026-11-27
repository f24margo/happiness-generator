# Жанры подписей. Чтобы добавить жанр, скопируйте один блок
# внутри CAPTION_GENRES и поменяйте код, название и текст.

CAPTION_GENRES = {
    "none": {"label": "🚫 Без подписи", "text": None},
    "quote": {
        "label": "💭 Цитата с поворотом",
        "text": (
            "a short wise quote-style line with an unexpected witty twist, "
            "in original wording, 2-3 sentences at most; "
            "do not name or attribute it to any real author"
        ),
    },
    "joke": {
        "label": "😄 Шутка",
        "text": "a short good-natured joke about the picture or the character, 2-3 sentences at most",
    },
    "congrat": {
        "label": "🎉 Поздравление",
        "text": "a warm, witty congratulation, 3-4 sentences",
    },
    "toast": {
        "label": "🥂 Тост",
        "text": "a short, warm toast with a smile, 3-4 sentences",
    },
}

# Тон подписи следует за силой шаржа
CAPTION_TONES = {
    "soft": "Tone: warm and gently ironic.",
    "fun": "Tone: lively and playful.",
    "satire": (
        "Tone: sharper and kindly satirical; aim the joke at behavior or a human trait, "
        "never at the person's body, age or looks."
    ),
}


def caption_request(genre, level, topic):
    """Фраза для запроса к ИИ. Пустая строка, если подпись не нужна."""
    data = CAPTION_GENRES.get(genre)
    if not data or not data["text"]:
        return ""
    parts = [
        "After the image, write a caption for it in Russian as a separate chat message "
        "(never inside the picture):",
        data["text"] + ".",
        CAPTION_TONES.get(level, CAPTION_TONES["soft"]),
    ]
    topic = (topic or "").strip()
    if topic:
        parts.append(f"Topic, occasion or name to use: {topic}.")
    parts.append("Do not attribute the text to any real person.")
    return " ".join(parts)