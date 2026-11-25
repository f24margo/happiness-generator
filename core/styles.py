# Реестр стилей. Чтобы добавить новый стиль, скопируйте один блок
# внутри STYLES, поменяйте код (например "pen") и тексты.

DEFAULT_STYLE = "gouache"

STYLES = {
    "gouache": {
        "names": {
            "ru": "🎨 Гуашь и акварель",
            "uk": "🎨 Гуаш і акварель",
            "en": "🎨 Gouache & watercolor",
            "es": "🎨 Gouache y acuarela",
        },
        "photo": (
            "editorial gouache and watercolor caricature illustration, "
            "expressive and playful, clean colorful brushstrokes on warm paper, "
            "no text, no signature"
        ),
        "hero": None,
    },
    "pen": {
        "names": {
            "ru": "🖋 Перо и штриховка",
            "uk": "🖋 Перо і штрихування",
            "en": "🖋 Pen & cross-hatching",
            "es": "🖋 Pluma y sombreado",
        },
        "photo": (
            "traditional pen and ink portrait on an ivory sheet, "
            "cross-hatching technique, thousands of delicate fine ink lines, "
            "black ink only on ivory paper, monochrome, "
            "depth, texture and realistic shadows, careful precise line work, "
            "no color, no text, no signature"
        ),
        "hero": (
            "stylish editorial pen and ink cross-hatching illustration, "
            "black ink only on ivory paper, monochrome, thousands of delicate fine lines, "
            "expressive playful pose and witty props, no color, no signature, no text"
        ),
    },
}


def get_style_data(code):
    return STYLES.get(code) or STYLES[DEFAULT_STYLE]


def style_photo_prompt(code):
    return get_style_data(code)["photo"]


def style_hero_prompt(code, default_prompt):
    return get_style_data(code)["hero"] or default_prompt