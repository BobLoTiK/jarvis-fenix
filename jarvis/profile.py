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

Запись — через config_manager (единый FileLock, атомарная замена).
"""

import copy
import getpass
import json
import logging
import re
import threading
import time
from pathlib import Path

from jarvis import config_manager

log = logging.getLogger("jarvis.profile")

from jarvis import paths as _paths

BASE_DIR = Path(__file__).resolve().parent.parent
# profiles/ — в USER_DIR, а не рядом с кодом.
# Может содержать кириллицу — это ок (Vosk их не читает).
PROFILES_DIR = _paths.profiles_dir()
_OLD_PROFILE = _paths.user_dir() / "user_profile.json"
_OLD_DIALOG = _paths.user_dir() / "dialog.json"

# №76: один RLock вместо двух локов. Раньше _current_lock и _listeners_lock
# могли дать гонку: _current менялся, а подписчики читали memory со старым
# профилем. RLock реентерабельный — безопасен для вложенных вызовов.
_lock = threading.RLock()

_current: str | None = None
_listeners: list = []

# Кэш содержимого profile.json, ключ — путь файла.
# Профиль на процесс один (мьютекс в launcher.py), поэтому
# инвалидация нужна только при своей записи и при switch().
_cache: dict[Path, dict] = {}


# ---------------------------------------------------------------
# Служебное
# ---------------------------------------------------------------

def _sanitize(name: str) -> str:
    """Приводит имя к безопасному имени папки."""
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
    with _lock:
        cur = current()
    path = PROFILES_DIR / _sanitize(cur)
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
    """Переносит старые user_profile.json и dialog.json в profiles/<user>/."""
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
    with _lock:
        if _current is None:
            _current = _windows_user()
        return _current


def subscribe(callback) -> None:
    """Регистрирует callback(old_name, new_name) — вызывается при switch()."""
    with _lock:
        if callback in _listeners:
            return
        _listeners.append(callback)


def unsubscribe(callback) -> None:
    """Удаляет подписку."""
    with _lock:
        try:
            _listeners.remove(callback)
        except ValueError:
            pass


def switch(name: str) -> str:
    """Переключает текущий профиль. Создаёт папку, если нет.

    №76: всё под одним _lock. Пока _current меняется и уведомляются
    подписчики — другие потоки не могут читать profile_dir()/memory.
    """
    global _current
    safe = _sanitize(name)

    with _lock:
        old_name = _current or _windows_user()

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
        else:
            # Профиль существует — если name нет, ставим его.
            # Иначе "я — Максим" на старом профиле вернёт старое имя
            # (например, "тест" из стресс-теста).
            try:
                raw = profile_file.read_text(encoding="utf-8")
                if raw.strip():
                    d = json.loads(raw)
                    if not d.get("name"):
                        d["name"] = name.strip()[:60] or safe
                        config_manager.save(d, path=profile_file)
                        log.info("Профиль %s: добавлено name = %r",
                                 safe, d["name"])
            except Exception:
                log.exception("Не удалось проверить name в профиле %s", safe)

        _current = safe

        # Профиль другой — кэш прошлого больше не действителен.
        # Сбрасываем под тем же локом, что и _current, чтобы
        # подписчики не прочитали кэш старого профиля.
        _cache_invalidate()

        # human — читаем имя из нового профиля
        human = safe
        try:
            raw = profile_file.read_text(encoding="utf-8")
            if raw.strip():
                d = json.loads(raw)
                human = d.get("name") or safe
        except Exception:
            log.exception("Не удалось прочитать name из нового профиля")

        log.info("Активный профиль: %s (%s → %s)", human, old_name, safe)

        # Уведомляем подписчиков под тем же локом
        listeners = list(_listeners)

    # Вызываем подписчиков ВНЕ лока, но с уже обновлённым _current.
    # Подписчики (IntentHandler._on_profile_switch) перечитывают dialog —
    # к этому моменту _current уже новый.
    for cb in listeners:
        try:
            cb(old_name, safe)
        except Exception:
            log.exception("Подписчик profile упал на switch(%r)", safe)

    return f"Профиль переключён на {human}."


def list_all() -> list[str]:
    """Список доступных профилей (имена папок)."""
    _ensure_dir(PROFILES_DIR)
    return sorted(p.name for p in PROFILES_DIR.iterdir() if p.is_dir())


def delete(name: str) -> bool:
    """Удаляет папку профиля. Активный — нельзя."""
    import shutil
    safe = _sanitize(name)
    with _lock:
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
            log.warning(
                "send2trash не установлен — профиль удаляется НАВСЕГДА"
            )
            shutil.rmtree(path)
            log.info("Профиль удалён: %s", safe)
        _cache_invalidate(path / "profile.json")
        return True
    except Exception:
        log.exception("Не удалось удалить профиль %s", safe)
        return False


# ---------------------------------------------------------------
# Чтение / запись полей профиля
# ---------------------------------------------------------------

def _safe_load() -> dict:
    """Читает profile.json ЧЕРЕЗ КЭШ В ПАМЯТИ.

    Раньше каждый profile.get() лез на диск. Из-за этого
    mood.effective_rate() — а его зовут на каждом синтезируемом
    предложении — и persona/mood/learning.build_prompt_block(),
    три чтения на каждый LLM-вызов, долбили файл в %APPDATA%.

    Отдаём КОПИЮ: часть вызывающих мутирует результат на месте
    (learning.add_fact правит facts[key] ещё до profile.set),
    и без копии они бы тихо правили кэш.
    """
    path = profile_path()

    with _lock:
        cached = _cache.get(path)
    if cached is not None:
        return copy.deepcopy(cached)

    if not path.exists():
        return {}

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        log.exception("Не удалось прочитать %s", path)
        return {}

    if not raw.strip():
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("Профиль %s битый — НЕ перезаписываю. Почини вручную.", path)
        raise

    if not isinstance(data, dict):
        log.warning("%s — не словарь, игнорирую", path)
        return {}

    with _lock:
        _cache[path] = data
    return copy.deepcopy(data)


def _cache_store(path: Path, data: dict) -> None:
    """Кладёт данные в кэш после успешной записи на диск."""
    with _lock:
        _cache[path] = data


def _cache_invalidate(path: Path | None = None) -> None:
    """Сбрасывает кэш. Без пути — весь (при switch / init / delete)."""
    with _lock:
        if path is None:
            _cache.clear()
        else:
            _cache.pop(path, None)


def get(key: str, default=None):
    try:
        return _safe_load().get(key, default)
    except json.JSONDecodeError:
        return default


def set(key: str, value) -> bool:
    with _lock:
        try:
            data = _safe_load()
        except json.JSONDecodeError:
            return False
        data[key] = value
        data.setdefault("created_at", time.time())
        path = profile_path()
        ok = config_manager.save(data, path=path)
        if ok:
            _cache_store(path, data)
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
    with _lock:
        try:
            data = _safe_load()
        except json.JSONDecodeError:
            return False
        if key not in data:
            return False
        del data[key]
        path = profile_path()
        ok = config_manager.save(data, path=path)
        if ok:
            _cache_store(path, data)
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
    """Вызывается при старте Феникса."""
    global _current
    _ensure_dir(PROFILES_DIR)
    with _lock:
        _current = _windows_user()
    _cache_invalidate()
    _migrate_old()

    user_dir = profile_dir()
    profile_file = user_dir / "profile.json"
    if not profile_file.exists():
        data = {"name": _windows_user(), "created_at": time.time()}
        config_manager.save(data, path=profile_file)
        log.info("Создан профиль по умолчанию: %s", profile_file)
    log.info("Активный профиль: %s (%s)", current(), user_dir.name)