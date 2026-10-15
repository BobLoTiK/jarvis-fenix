"""Query-scoped personal memory. Absence/uncertainty never means 'send everything'."""

from dataclasses import dataclass
import re

from jarvis.language.morphology import parses


@dataclass(frozen=True)
class Selection:
    profile: dict
    facts: dict


PERSONAL = frozenset(("я", "мой", "свой", "себя"))
RECALL = frozenset(("помнить", "запомнить", "сохранить", "упоминать"))
RECOMMEND = frozenset(("посоветовать", "порекомендовать", "подобрать", "рекомендовать"))
PREFERENCES = frozenset(
    ("интерес", "предпочтение", "увлечение", "любимый", "нравиться")
)
PROFILE_TOPICS = {
    "name": frozenset(("имя", "звать", "называться")),
    "default_city": frozenset(("город", "жить", "проживать", "местоположение")),
}
# Function words are not evidence that two memories share a topic.
GENERIC = frozenset(
    (
        "я",
        "мой",
        "свой",
        "себя",
        "ты",
        "мы",
        "он",
        "она",
        "оно",
        "они",
        "что",
        "кто",
        "какой",
        "который",
        "чей",
        "где",
        "как",
        "когда",
        "сколько",
        "это",
        "тот",
        "этот",
        "весь",
        "быть",
        "мочь",
        "хотеть",
        "сказать",
        "рассказать",
        "знать",
        "помнить",
        "запомнить",
        "сохранить",
        "упоминать",
        "посоветовать",
        "порекомендовать",
        "подобрать",
        "рекомендовать",
        "любимый",
        "нравиться",
        "интерес",
        "предпочтение",
        "увлечение",
        "пожалуйста",
        "что-нибудь",
        "нибудь",
    )
)


def lemmas(text):
    return frozenset(
        p.normal_form.replace("ё", "е")
        for w in re.findall(r"[А-Яа-яЁё]+", text.lower())
        for p in parses(w)[:1]
        if p.tag.POS not in ("PREP", "CONJ", "PRCL", "INTJ")
    )


def select_memory(query, profile_values, facts, limit=5):
    if not isinstance(query, str) or not query.strip():
        return Selection({}, {})
    words = lemmas(query)
    personal = bool(words & PERSONAL)
    recall = bool(words & RECALL)
    preference_request = bool(words & RECOMMEND) and (
        personal or bool(words & PREFERENCES)
    )
    nearby = "рядом" in words and personal
    # A standalone «расскажи что-нибудь» (even «мне») is not a memory request.
    if not (personal or recall or preference_request or nearby):
        return Selection({}, {})
    topics = words - GENERIC
    overview = recall and not topics
    selected_profile = {}
    for key, cues in PROFILE_TOPICS.items():
        if profile_values.get(key) and (
            overview
            or personal
            and bool(words & cues)
            or key == "default_city"
            and nearby
        ):
            selected_profile[key] = profile_values[key]
    selected_facts = {}
    for key, value in facts.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        key_words = lemmas(key)
        related = bool(topics & (key_words - GENERIC))
        preference = preference_request and not topics and bool(key_words & PREFERENCES)
        if overview or related or preference:
            if value in selected_profile.values():
                continue
            selected_facts[key] = value
            if len(selected_facts) >= limit:
                break
    return Selection(selected_profile, selected_facts)
