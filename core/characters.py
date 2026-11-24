CULTURE_PROMPTS = {
    "ru": "Language: natural, sharp, modern Russian. No folk clichés or repetitive authors. Draw freely from global wit, world philosophy, dark humor, stand-up comedy, and razor-sharp aphorisms (from Seneca, Schopenhauer, Oscar Wilde, Churchill, and Ranevskaya to modern psychology).",
    "uk": "Language: natural, witty, modern Ukrainian. Avoid folkloric clichés or repetitive local names. Draw freely from global wit, world philosophy, dark humor, stand-up comedy, and razor-sharp aphorisms from all eras and cultures.",
    "en": "Language: sharp, witty, cosmopolitan English. Draw freely from global philosophy, British/American stand-up, Oscar Wilde, Mark Twain, George Carlin, and cynical world wisdom.",
    "es": "Language: vibrant, witty, modern Spanish. Draw freely from global irony, philosophical paradoxes, sharp stand-up humor, and universal human wisdom across all eras."
}

CHARACTER_PROMPTS = {
    "girl": (
        "Consistent recurring character: Maya, a stylish 25-year-old woman with wavy chestnut hair in a messy bun, "
        "expressive green eyes, freckles, wearing a mustard-yellow knit sweater and round brass earrings."
    ),
    "boy": (
        "Consistent recurring character: Leo, a charismatic 28-year-old man with tousled dark curly hair, "
        "light stubble, expressive thick eyebrows, wearing a rolled-up denim shirt over a white tee."
    ),
    "grandma": (
        "Consistent recurring character: Baba Zina, a witty 70-year-old grandmother with silver hair in a tight bun, "
        "large round tortoiseshell glasses, rosy cheeks, wearing a cozy emerald-green knitted cardigan over a floral blouse."
    ),
    "grandpa": (
        "Consistent recurring character: Ded Makar, a colorful 75-year-old grandfather with a bushy white mustache, "
        "tufts of white hair on the sides, expressive bushy eyebrows, wearing a brown tweed vest over a checkered shirt."
    ),
    "cat": (
        "Consistent recurring character: Aristarchus, a plump fluffy ginger-and-white cat with huge expressive amber eyes, "
        "wearing a tiny striped red-and-blue knitted scarf."
    )
}

VISUAL_RULES = (
    " Visual rules for image_scene: keep the eyes natural and the face recognizable; "
    "show the emotion only with the mouth, eyebrows, head tilt and hands. "
    "Never put any text, letters, signs, neon signs, posters, banners or logos in the scene."
)

MOOD_PROMPTS = {
    "warm": (
        "Mood: Intellectual flirtation and charming sarcasm. Give a clever, slightly teasing compliment "
        "mixed with witty global irony, never cheesy or overly sweet. "
        "Scene idea: soft golden-hour light, a cup of coffee or a small bouquet in hand, "
        "a confident friendly smile with one playfully raised eyebrow."
        + VISUAL_RULES
    ),
    "wisdom": (
        "Mood: Razor-sharp world sarcasm and paradoxical philosophy. Twist famous global wisdom "
        "(stoics, cynics, writers, comedians) into an unexpectedly funny, slightly ruthless observation "
        "about life or love. "
        "Scene idea: a cozy study with shelves of books, a chess board or a candle, "
        "a thoughtful half-smile with one raised eyebrow, holding an open book."
        + VISUAL_RULES
    ),
    "greed": (
        "Mood: Merciless satire on GREED and materialism. "
        "Scene idea: hugging a giant piggy bank or a heap of gold coins, a sly smirk, "
        "eyebrows raised, protective comedic possessiveness with the hands."
        + VISUAL_RULES
    ),
    "flattery": (
        "Mood: Venomous satire on SWEET FLATTERY and hypocrisy. "
        "Scene idea: an over-the-top sugar-sweet smile, rolling out a red carpet or holding a golden crown, "
        "with one hand hidden behind the back and fingers crossed."
        + VISUAL_RULES
    ),
    "lust": (
        "Mood: Playful, tasteful PG-13 satire on PASSION, DESIRE and FLIRTATION. Dramatic comedy vibe, "
        "mocking human instincts with witty charm. "
        "Scene idea: a candle-lit dinner table, a single rose in hand, a charming wink and a playful smile. "
        "Fully dressed, nothing revealing."
        + VISUAL_RULES
    ),
}