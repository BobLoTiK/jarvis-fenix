"""Профиль пользователя — мультипрофиль.

Архитектура:
    profiles/
    ├── default.json      ← если Windows-юзер неизвестен
    ├── BobLoTiK.json     ← профиль по Windows-юзеру
    └── masha.json        ← «Феникс, я — Маша» создаст этот файл

Логика:
    - При старте: getpass.getuser() → имя Windows-юзера.
    - Если profiles/<windows_user>.json есть — используется.
    - Если нет — создаётся (с миграцией из старого user_profile.json).
    - «Феникс, я — Маша» → переключает на profiles/masha.json.

Хранит:
    - name — человеческое имя
    - default_city — город для погоды
    - tts_voice — голос
    - facts — произвольные факты («запомни: ...»)
    - created_at — timestamp создания

Файлы в .gitignore (profiles/).
Запись — через config_manager (единый FileLock, атомарная замена).
"""

import getpass
import json
import logging
import re
import time
from pathlib import Path

from jarvis import config_manager

log = logging.getLogger("jarvis.profile")

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = BASE_DIR / "profiles"
_OLD_PROFILE = BASE_DIR / "user_profile.json"

# Кэш текущего профиля — чтобы не читать файл каждый раз
_current: str | None = None


# ---------------------------------------------------------------
# Служебное
# ---------------------------------------------------------------

def _sanitize(name: str) -> str:
    """Приводит имя к безопасному имени файла.

    «Маша» → «masha» (транслит), «Bob Lo» → «bob_lo».
    Пустое → «default».
    """
    if not name:
        return "default"
    name = name.strip().lower()
    # транслит кириллицы
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    name = "".join(translit.get(ch, ch) for ch in name)
    # только [a-z0-9_-]
    name = re.sub(r"[^a-z0-9_-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "default"


def _path_for(name: str) -> Path:
    return PROFILES_DIR / f"{_sanitize(name)}.json"


def _ensure_dir() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def _windows_user() -> str:
    """Имя Windows-пользователя. Fallback — default."""
    try:
        return getpass.getuser() or "default"
    except Exception:
        return "default"


# ---------------------------------------------------------------
# Миграция старого user_profile.json
# ---------------------------------------------------------------

def _migrate_old_profile() -> None:
    """Если есть старый user_profile.json — переносим в profiles/<user>.json.

    Старый файл НЕ удаляем — на случай, если что-то пойдёт не так.
    """
    if not _OLD_PROFILE.exists():
        return
    _ensure_dir()
    target = _path_for(_windows_user())
    if target.exists():
        return  # уже мигрировали
    try:
        data = json.loads(_OLD_PROFILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        data.setdefault("created_at", time.time())
        config_manager.save(data, path=target)
        log.info("Миграция профиля: %s → %s", _OLD_PROFILE.name, target.name)
    except Exception:
        log.exception("Не удалось мигрировать старый профиль")


# ---------------------------------------------------------------
# Текущий профиль
# ---------------------------------------------------------------

def current() -> str:
    """Имя текущего активного профиля (без .json)."""
    global _current
    if _current is None:
        _current = _windows_user()
    return _current


def switch(name: str) -> str:
    """Переключает текущий профиль. Создаёт файл, если нет.

    Возвращает человекочитаемый ответ.
    """
    global _current
    _ensure_dir()
    safe = _sanitize(name)
    path = PROFILES_DIR / f"{safe}.json"

    if not path.exists():
        data = {
            "name": name.strip()[:60] or safe,
            "created_at": time.time(),
        }
        config_manager.save(data, path=path)
        log.info("Создан новый профиль: %s", path.name)

    _current = safe
    human = get("name", safe)
    log.info("Активный профиль: %s (%s)", human, path.name)
    return f"Профиль переключён на {human}."


def list_all() -> list[str]:
    """Список доступных профилей (без .json)."""
    _ensure_dir()
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))


# ---------------------------------------------------------------
# Чтение / запись полей
# ---------------------------------------------------------------

def _current_path() -> Path:
    return _path_for(current())


def _safe_load() -> dict:
    """Читает текущий профиль. Возвращает {} при отсутствии.

    При битом JSON — логирует и НЕ перезаписывает (raise).
    """
    path = _current_path()
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        log.error("Профиль %s битый — НЕ перезаписываю. Почини вручную.", path)
        raise


def get(key: str, default=None):
    """Читает одно поле. При битом файле — возвращает default."""
    try:
        return _safe_load().get(key, default)
    except json.JSONDecodeError:
        return default


def set(key: str, value) -> bool:
    """Записывает одно поле. При битом файле — НЕ перезаписывает."""
    try:
        data = _safe_load()
    except json.JSONDecodeError:
        return False

    data[key] = value
    data.setdefault("created_at", time.time())
    ok = config_manager.save(data, path=_current_path())
    if ok:
        log.info("Профиль %s: %s = %r", current(), key, value)
    else:
        log.error("Профиль %s: не удалось сохранить %s", current(), key)
    return ok


def all_data() -> dict:
    try:
        return _safe_load()
    except json.JSONDecodeError:
        return {}


def forget(key: str) -> bool:
    try:
        data = _safe_load()
    except json.JSONDecodeError:
        return False
    if key not in data:
        return False
    del data[key]
    ok = config_manager.save(data, path=_current_path())
    if ok:
        log.info("Профиль %s: удалено %s", current(), key)
    return ok


# ---------------------------------------------------------------
# Факты («запомни: ...»)
# ---------------------------------------------------------------

def set_fact(key: str, value: str) -> bool:
    """Сохраняет факт в facts.<key>."""
    facts = get("facts", {}) or {}
    facts[key] = value
    return set("facts", facts)


def get_fact(key: str, default=None):
    facts = get("facts", {}) or {}
    return facts.get(key, default)


def all_facts() -> dict:
    return get("facts", {}) or {}


def forget_fact(key: str) -> bool:
    facts = get("facts", {}) or {}
    if key not in facts:
        return False
    del facts[key]
    return set("facts", facts)


# ---------------------------------------------------------------
# Инициализация при старте
# ---------------------------------------------------------------

def init() -> None:
    """Вызывается при старте Феникса.

    - Мигрирует старый user_profile.json (если есть).
    - Создаёт текущий профиль, если его нет.
    - Логирует активный профиль.
    """
    global _current
    _migrate_old_profile()
    _ensure_dir()
    _current = _windows_user()
    path = _current_path()
    if not path.exists():
        data = {
            "name": _windows_user(),
            "created_at": time.time(),
        }
        config_manager.save(data, path=path)
        log.info("Создан профиль по умолчанию: %s", path.name)
    log.info("Активный профиль: %s (%s)", current(), path.name)