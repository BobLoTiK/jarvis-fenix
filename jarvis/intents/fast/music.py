"""Музыка — ДО open_fast.

«включи музыку» не должно уйти в open_app (яндекс музыка).
Сначала проверяем тут: play / pause / next / prev.
"""

import re

from jarvis import actions


def music_fast(handler, cmd: str) -> str | None:
    if re.search(r"(включи|врубай|играй|поставь)\s+(музыку|музыка|плейлист)", cmd):
        actions.media_key("play")
        return "Включаю музыку."

    if cmd in {"пауза", "плей", "play", "pause"}:
        actions.media_key("play")
        return "Готово."

    if re.search(r"^(включи|врубай)\s+(плей|музыку)$", cmd):
        actions.media_key("play")
        return "Включаю."

    if re.search(r"(следующ|дальше|переключи|переключ)\w*\s*(трек|песн|музык)?", cmd):
        if any(w in cmd for w in ("трек", "песн", "музык", "дальше")):
            actions.media_key("next")
            return "Переключаю."

    if re.search(r"(предыдущ|назад)\w*\s*(трек|песн|музык)", cmd):
        actions.media_key("prev")
        return "Возвращаю."

    if re.search(r"(останови|стоп)\s+(музык|трек|песн)", cmd):
        actions.media_key("play")
        return "Останавливаю."

    return None