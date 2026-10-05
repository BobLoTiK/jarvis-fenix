"""Профиль пользователя — мультипрофиль.

Архитектура:
    profiles/
    ├── default/
    │   ├── profile.json
    │   └── dialog.json
    ├── maksim/
    │   ├── profile.json
    │   └── dialog.json
    └── masha/
        ├── profile.json
        └── dialog.json

Логика:
    - При старте: getpass.getuser() → имя Windows-юзера.
    - Если profiles/<user>/profile.json есть — используется.
    - Если нет — создаётся (с миграцией из старого user_profile.json).
    - «Феникс, я — Маша» → переключает на profiles/masha/.

Хранит:
    - name — человеческое имя
    - default_city — город для погоды
    - tts_voice — голос
    - facts — произвольные факты («запомни: ...»)
    - created_at — timestamp создания

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
_OLD_DIALOG = BASE_DIR / "dialog.json"

# Кэш текущего профиля — чтобы не читать файл каждый раз
_current: str | None = None


# ---------------------------------------------------------------
# Служебное
# ---------------------------------------------------------------

def _sanitize(name: str) -> str:
    """Приводит имя к безопасному имени папки.

    «Маша» → «masha» (транслит), «Максим» → «maksim».
    Пустое → «default».
    """
    if not name:
        return "default"
    name = name.strip().lower()
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    name = "".join(translit.get(ch, ch) for ch in name)
    name = re.sub(r"[^a-z0-9_-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "default"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _windows_user() -> str:
    """Имя Windows-пользователя. Fallback — default."""
    try:
        return getpass.getuser() or "default"
    except Exception:
        return "default"


# ---------------------------------------------------------------
# Пути
# ---------------------------------------------------------------

def profile_dir() -> Path:
    """Папка текущего профиля. Создаётся при вызове."""
    path = PROFILES_DIR / _sanitize(current())
    _ensure_dir(path)
    return path


def profile_path() -> Path:
    """Путь к profile.json текущего профиля."""
    return profile_dir() / "profile.json"


def dialog_path() -> Path:
    """Путь к dialog.json текущего профиля."""
    return profile_dir() / "dialog.json"


# ---------------------------------------------------------------
# Миграция
# ---------------------------------------------------------------

def _migrate_old() -> None:
    """Переносит старые user_profile.json и dialog.json в profiles/<user>/.

    Старые файлы НЕ удаляем — на случай, если что-то пойдёт не так.
    """
    if not PROFILES_DIR.exists():
        return
    user_dir = PROFILES_DIR / _sanitize(_windows_user())
    _ensure_dir(user_dir)

    new_profile = user_dir / "profile.json"
    if _OLD_PROFILE.exists() and not new_profile.exists():
        try:
            data = json.loads(_OLD_PROFILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("created_at", time.time())
                config_manager.save(data, path=new_profile)
                log.info("Миграция: %s → %s", _OLD_PROFILE.name, new_profile)
        except Exception:
            log.exception("Не удалось мигрировать старый профиль")

    new_dialog = user_dir / "dialog.json"
    if _OLD_DIALOG.exists() and not new_dialog.exists():
        try:
            data = json.loads(_OLD_DIALOG.read_text(encoding="utf-8"))
            if isinstance(data, list):
                new_dialog.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                log.info("Миграция: %s → %s", _OLD_DIALOG.name, new_dialog)
        except Exception:
            log.exception("Не удалось мигрировать старый диалог")


# ---------------------------------------------------------------
# Текущий профиль
# ---------------------------------------------------------------

def current() -> str:
    """Имя текущего активного профиля (папки)."""
    global _current
    if _current is None:
        _current = _windows_user()
    return _current


def switch(name: str) -> str:
    """Переключает текущий профиль. Создаёт папку, если нет."""
    global _current
    safe = _sanitize(name)
    user_dir = PROFILES_DIR / safe
    _ensure_dir(user_dir)

    profile_file = user_dir / "profile.json"
    if not profile_file.exists():
        data = {
            "name": name.strip()[:60] or safe,
            "created_at": time.time(),
        }
        config_manager.save(data, path=profile_file)
        log.info("Создан новый профиль: %s", profile_file)

    _current = safe
    human = get("name", safe)
    log.info("Активный профиль: %s (%s)", human, safe)
    return f"Профиль переключён на {human}."


def list_all() -> list[str]:
    """Список доступных профилей (имена папок)."""
    _ensure_dir(PROFILES_DIR)
    return sorted(p.name for p in PROFILES_DIR.iterdir() if p.is_dir())


def delete(name: str) -> bool:
    """Удаляет папку профиля. Активный — нельзя.

    Перемещает в корзину, если доступно (send2trash).
    Иначе — простое удаление.
    """
    import shutil
    safe = _sanitize(name)
    if safe == current():
        log.warning("Нельзя удалить активный профиль: %s", safe)
        return False
    path = PROFILES_DIR / safe
    if not path.exists() or not path.is_dir():
        return False
    try:
        try:
            from send2trash import send2trash
            send2trash(str(path))
            log.info("Профиль перемещён в корзину: %s", safe)
        except ImportError:
            shutil.rmtree(path)
            log.info("Профиль удалён: %s", safe)
        return True
    except Exception:
        log.exception("Не удалось удалить профиль %s", safe)
        return False


# ---------------------------------------------------------------
# Чтение / запись полей профиля
# ---------------------------------------------------------------

def _safe_load() -> dict:
    path = profile_path()
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
    try:
        return _safe_load().get(key, default)
    except json.JSONDecodeError:
        return default


def set(key: str, value) -> bool:
    try:
        data = _safe_load()
    except json.JSONDecodeError:
        return False
    data[key] = value
    data.setdefault("created_at", time.time())
    ok = config_manager.save(data, path=profile_path())
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
    ok = config_manager.save(data, path=profile_path())
    if ok:
        log.info("Профиль %s: удалено %s", current(), key)
    return ok


# ---------------------------------------------------------------
# Факты
# ---------------------------------------------------------------

def set_fact(key: str, value: str) -> bool:
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

    - Мигрирует старые user_profile.json и dialog.json.
    - Создаёт папку текущего профиля, если нет.
    - Логирует активный профиль.
    """
    global _current
    _ensure_dir(PROFILES_DIR)
    _current = _windows_user()
    _migrate_old()

    user_dir = profile_dir()
    profile_file = user_dir / "profile.json"
    if not profile_file.exists():
        data = {"name": _windows_user(), "created_at": time.time()}
        config_manager.save(data, path=profile_file)
        log.info("Создан профиль по умолчанию: %s", profile_file)
    log.info("Активный профиль: %s (%s)", current(), user_dir.name)