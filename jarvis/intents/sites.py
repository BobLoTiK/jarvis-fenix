"""Сайты для открытия голосом — ленивая загрузка из packs/sites.json.

Fallback — хардкод (если packs/sites.json нет или битый).
Кэш — глобальный, инициализируется при первом обращении.
"""

import json
import logging

log = logging.getLogger("jarvis.intents")


_SITES_FALLBACK = {
    "ютуб": ("Ютуб", "https://www.youtube.com"),
    "гугл": ("Гугл", "https://www.google.com"),
    "яндекс": ("Яндекс", "https://ya.ru"),
    "гитхаб": ("Гитхаб", "https://github.com"),
    "вк": ("ВКонтакте", "https://vk.com"),
    "вконтакте": ("ВКонтакте", "https://vk.com"),
    "твич": ("Твич", "https://www.twitch.tv"),
    "кинопоиск": ("Кинопоиск", "https://www.kinopoisk.ru"),
    "википедия": ("Википедию", "https://ru.wikipedia.org"),
    "почта": ("Почту", "https://mail.google.com"),
}


def _load_sites() -> dict:
    """Загружает sites.json из packs/. Fallback — хардкод."""
    sites = dict(_SITES_FALLBACK)
    try:
        from jarvis.packs import PACKS_DIR
        path = PACKS_DIR / "sites.json"
        if not path.exists():
            return sites
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return sites
        for entry in data:
            action = entry.get("action", "")
            if not action.startswith(("http://", "https://")):
                continue
            for phrase in entry.get("phrases", []):
                # «открой ютуб» → ключ «ютуб»
                key = phrase.lower().replace("открой", "").strip()
                if key and key not in sites:
                    title = entry.get("reply", key).replace("Открываю ", "").rstrip(".")
                    sites[key] = (title, action)
        log.info("SITES загружены из packs/sites.json: %d записей", len(sites))
    except Exception:
        log.exception("Не удалось загрузить packs/sites.json — fallback на хардкод")
    return sites


_SITES_CACHE: dict | None = None


def get_sites() -> dict:
    """Ленивая загрузка SITES — при первом обращении, не при импорте."""
    global _SITES_CACHE
    if _SITES_CACHE is None:
        _SITES_CACHE = _load_sites()
    return _SITES_CACHE