"""Векторная память фактов (RAG) — на профиль.

Архитектура:
    profiles/<user>/memory_index.json — кэш: факты из profile.json + их векторы.
    Источник правды — profile.json (ключ facts). Индекс можно удалить в любой
    момент: он пересоберётся из профиля. Реплики диалога здесь не хранятся
    и не индексируются (короткая память — memory.py / dialog.json).

Эмбеддинги:
    Локальная Ollama (POST /api/embed), запросы — stdlib urllib, как в brain.py.
    Модель — config «memory_rag_model» (по умолчанию nomic-embed-text).
    Косинус — numpy (он уже в requirements, import ленивый).

Деградация:
    Эмбеддингов нет — лексический поиск. И он не уверен — блок не добавляется,
    и brain берёт ВСЕ факты, как раньше. Фича выключена по умолчанию
    (memory_rag_enabled = False, как observer_enabled).

API:
    set_config(config)               — принять конфиг (образец weather.set_config)
    status()                         — для GUI и команд
    search(query, k)                 — [{key, value, score}], работает и без Ollama
    build_prompt_block(query, k)     — блок фактов для промпта или ""
    sync(force)                      — сверка индекса с profile.json
    index_fact(key, value)           — хук learning.add_fact (фон)
    forget_fact(key)                 — хук learning.forget_fact (фон)
    warmup_async() / stop() / on_config_change(k, v) / reset_for_tests()
"""

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from difflib import SequenceMatcher

from jarvis import config_manager, profile

log = logging.getLogger("jarvis.vectormem")

SCHEMA_VERSION = 1
DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
BREAKER_SEC = 300.0
BREAKER_FAILS = 3
CACHE_MAX = 64

_lock = threading.RLock()
_config = None

# Состояние эмбеддингов.
_legacy_api = False          # Ollama без /api/embed — ходим в /api/embeddings
_fails = 0                   # ошибок подряд
_breaker_until = 0.0         # до этого времени эмбеддинги не пробуем
_said_no_model = False       # предупреждение про ollama pull — один раз
_embed_cache: "OrderedDict[str, list]" = OrderedDict()

# Кэш индекса в RAM: перечитываем только при смене файла.
_items_cache = {"stamp": None, "items": [], "matrix": None}

# Фоновый воркер индексации.
_worker = None
_wake = threading.Event()
_stop = threading.Event()


# ---------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------

def set_config(config) -> None:
    """Принимает конфиг приложения (как weather.set_config)."""
    global _config
    _config = config
    log.info("Конфиг принят: модель %s", _model())


def _cfg(key, default=None):
    if _config is None:
        return default
    try:
        return _config.get(key, default)
    except Exception:
        log.exception("Не удалось прочитать ключ %s", key)
        return default


def _enabled() -> bool:
    """Фича включена? Выключена — ни одного сетевого вызова."""
    return bool(_cfg("memory_rag_enabled", False))


def _model() -> str:
    return str(_cfg("memory_rag_model", DEFAULT_MODEL) or DEFAULT_MODEL)


def _ollama_url() -> str:
    url = str(_cfg("ollama_url", DEFAULT_OLLAMA_URL) or DEFAULT_OLLAMA_URL)
    return url.rstrip("/")


def _top_k() -> int:
    try:
        return max(1, int(_cfg("memory_rag_top_k", 3) or 3))
    except (TypeError, ValueError):
        return 3


def _min_score() -> float:
    """Порог косинуса. У nomic шкала сжатая (релевантное 0.66–0.74,
    случайное 0.57–0.63), поэтому дефолт 0.6, а не 0.35."""
    try:
        return float(_cfg("memory_rag_min_score", 0.6))
    except (TypeError, ValueError):
        return 0.6


def _margin() -> float:
    """Насколько лидер должен оторваться от второго места.

    У nomic шкала сжата настолько, что «просто выше порога» ничего не
    значит: на запрос «сколько сейчас времени» случайный факт набирает
    0.626, а релевантный на другой запрос — 0.633. Разделяет не порог,
    а отрыв: у настоящего совпадения он 0.08–0.14, у шума — 0.00–0.03.
    """
    try:
        return float(_cfg("memory_rag_margin", 0.04))
    except (TypeError, ValueError):
        return 0.04


def _lexical_min() -> float:
    """Порог лексического поиска — у него своя шкала (совпадение ~0.43)."""
    try:
        return float(_cfg("memory_rag_lexical_min_score", 0.35))
    except (TypeError, ValueError):
        return 0.35


def _timeout() -> float:
    try:
        return float(_cfg("memory_rag_timeout", 2.5) or 2.5)
    except (TypeError, ValueError):
        return 2.5


def _lexical_fallback() -> bool:
    return bool(_cfg("memory_rag_lexical_fallback", True))


def _background_timeout() -> float:
    """Таймаут для фоновых вызовов, где голосовой цикл не ждёт.

    Замерено 14.10.2026: первый вызов nomic-embed-text тянет ~20 с — Ollama
    грузит модель с диска. Горячему пути такие паузы противопоказаны
    (там 2.5 с), а фону — можно.
    """
    return max(60.0, _timeout() * 4)


# ---------------------------------------------------------------
# Эмбеддинги (Ollama, stdlib urllib)
# ---------------------------------------------------------------

def _apply_prefix(text: str, kind: str) -> str:
    """Префиксы nomic: документы и запросы асимметричны.

    Ollama их не подставляет, а без них косинусы слипаются в один кластер
    и порог отсечения перестаёт что-либо значить. Для симметричных моделей
    (bge/mxbai) префиксы, наоборот, запрещены.
    """
    if "nomic" in _model().lower():
        return ("search_query: " if kind == "query" else "search_document: ") + text
    return text


def _post(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _note_ok() -> None:
    global _fails, _breaker_until, _said_no_model
    _fails = 0
    _breaker_until = 0.0
    _said_no_model = False


def _note_fail(msg: str, *args) -> None:
    global _fails, _breaker_until
    _fails += 1
    log.warning(msg, *args)
    if _fails >= BREAKER_FAILS:
        _breaker_until = time.time() + BREAKER_SEC
        log.warning("Эмбеддинги недоступны — пауза %.0f с (лексический поиск)",
                    BREAKER_SEC)


def embed_texts(texts: list, kind: str = "document", timeout: float = None):
    """Векторы для текстов. None — эмбеддинги недоступны.

    kind: "document" (индексация) | "query" (поиск).
    """
    global _legacy_api, _said_no_model
    if not texts:
        return []
    if not _enabled():
        return None
    if time.time() < _breaker_until:
        return None

    model = _model()
    t = float(timeout or _timeout())

    try:
        if not _legacy_api:
            payload = {
                "model": model,
                "input": [_apply_prefix(x, kind) for x in texts],
                "keep_alive": -1,
            }
            data = _post(_ollama_url() + "/api/embed", payload, t)
            vecs = data.get("embeddings")
            if not isinstance(vecs, list) or len(vecs) != len(texts):
                _note_fail("Ollama вернула неожиданный ответ /api/embed")
                return None
        else:
            vecs = _embed_legacy(texts, kind, t, model)
            if vecs is None:
                return None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        if "try pulling" in body or ("not found" in body and "model" in body):
            if not _said_no_model:
                _said_no_model = True
                _note_fail("Модель эмбеддингов %r не скачана — "
                           "выполни «ollama pull %s»", model, model)
            else:
                _note_fail("Модель эмбеддингов %r недоступна", model)
            return None
        if e.code == 404 and not _legacy_api:
            log.info("Ollama не знает /api/embed — перехожу на /api/embeddings")
            _legacy_api = True
            try:
                vecs = _embed_legacy(texts, kind, t, model)
            except Exception:
                _note_fail("Эмбеддинги недоступны (legacy /api/embeddings)")
                return None
            if vecs is None:
                return None
        else:
            _note_fail("Эмбеддинги: HTTP %s", getattr(e, "code", "?"))
            return None
    except Exception as e:
        _note_fail("Эмбеддинги недоступны: %s", e)
        return None

    for v in vecs:
        if not isinstance(v, list) or not v:
            _note_fail("Эмбеддинги: пустой вектор в ответе")
            return None

    _note_ok()
    return vecs


def _embed_legacy(texts: list, kind: str, timeout: float, model: str):
    """Старый /api/embeddings — по одному тексту за вызов."""
    out = []
    for text in texts:
        payload = {"model": model, "prompt": _apply_prefix(text, kind)}
        data = _post(_ollama_url() + "/api/embeddings", payload, timeout)
        vec = data.get("embedding")
        if not isinstance(vec, list) or not vec:
            return None
        out.append(vec)
    return out


def embed_cached(text: str, kind: str = "query"):
    """То же, но с LRU-кэшем — для горячего пути диалога."""
    key = f"{kind}\x00{text}"
    with _lock:
        if key in _embed_cache:
            _embed_cache.move_to_end(key)
            return _embed_cache[key]
    vecs = embed_texts([text], kind=kind)
    if not vecs:
        return None
    with _lock:
        _embed_cache[key] = vecs[0]
        _embed_cache.move_to_end(key)
        while len(_embed_cache) > CACHE_MAX:
            _embed_cache.popitem(last=False)
    return vecs[0]


# ---------------------------------------------------------------
# Индекс: чтение / запись
# ---------------------------------------------------------------

def index_path():
    """Путь к индексу текущего профиля."""
    return profile.memory_index_path()


def _valid(data: dict) -> bool:
    """Индекс годится? Модель и версия должны совпадать.

    Векторы разных моделей несравнимы, поэтому при смене модели индекс
    игнорируется целиком, а не «частично».
    """
    if not isinstance(data, dict):
        return False
    if data.get("version") != SCHEMA_VERSION:
        return False
    if data.get("embed_model") != _model():
        return False
    return isinstance(data.get("items"), list)


def load_index() -> dict:
    """Читает индекс. Битый/устаревший — пустой словарь."""
    path = index_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Не удалось прочитать %s", path)
        return {}
    if not _valid(data):
        log.info("Индекс %s устарел (версия/модель) — пересоберу", path.name)
        return {}
    return data


def save_index(items: list, dim: int) -> bool:
    """Атомарно пишет индекс (config_manager: mkstemp + os.replace + FileLock)."""
    data = {
        "version": SCHEMA_VERSION,
        "embed_model": _model(),
        "dim": int(dim or 0),
        "updated_at": time.time(),
        "items": items,
    }
    return config_manager.save(data, path=index_path())


def _stamp(path):
    """Ключ кэша: путь + файл + модель.

    Модель обязательна в ключе: при её смене файл на диске не меняется,
    но индекс становится невалидным (векторы несравнимы).
    """
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size, _model())
    except OSError:
        return (str(path), None, None, _model())


def _items() -> list:
    """Элементы индекса из кэша (перечитывается только при смене файла)."""
    path = index_path()
    stamp = _stamp(path)
    with _lock:
        if _items_cache["stamp"] != stamp:
            data = load_index()
            _items_cache["stamp"] = stamp
            _items_cache["items"] = data.get("items", []) if data else []
            _items_cache["matrix"] = None
        return _items_cache["items"]


def _invalidate() -> None:
    with _lock:
        _items_cache["stamp"] = None
        _items_cache["matrix"] = None


# ---------------------------------------------------------------
# Факты (источник правды — profile.json)
# ---------------------------------------------------------------

def _facts() -> dict:
    """Факты из профиля. Импорт ленивый — иначе цикл learning ↔ vectormem."""
    try:
        from jarvis import learning
        facts = learning.all_facts()
        return facts if isinstance(facts, dict) else {}
    except Exception:
        log.exception("Не удалось прочитать факты профиля")
        return {}


def _items_from_facts() -> list:
    """Факты как элементы индекса — без векторов (индекс ещё не собран)."""
    return [{"key": k, "value": v, "text": f"{k}: {v}", "vec": None}
            for k, v in _facts().items()]


# ---------------------------------------------------------------
# Поиск
# ---------------------------------------------------------------

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]{3,}")


def _stems(text: str) -> set:
    """Грубые основы: первые 4 буквы слова (город/городе/города → «горо»)."""
    return {t[:4] for t in _TOKEN_RE.findall((text or "").lower())}


def _lexical_score(query: str, text: str) -> float:
    """Грубая близость запроса и факта.

    Главный вес — «покрытие»: какая доля меньшего набора слов совпала.
    «какой у меня город» ↔ «город: Казань» — одно общее слово из двух
    значащих, это уже уверенное совпадение, хотя Jaccard тут всего 0.25.
    """
    a, b = _stems(query), _stems(text)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    coverage = inter / min(len(a), len(b))
    jaccard = inter / len(a | b)
    ratio = SequenceMatcher(None, query.lower(), text.lower()).ratio()
    return 0.7 * coverage + 0.2 * jaccard + 0.1 * ratio


def _lexical_hits(query: str, items: list) -> list:
    hits = []
    for it in items:
        text = it.get("text") or f"{it.get('key', '')}: {it.get('value', '')}"
        score = _lexical_score(query, text)
        if score > 0:
            hits.append((score, it))
    return hits


def _matrix(items: list):
    """(vec_items, нормализованная матрица) или (None, None)."""
    with _lock:
        if _items_cache["matrix"] is not None:
            return _items_cache["matrix"]

    vec_items = [it for it in items if isinstance(it.get("vec"), list) and it["vec"]]
    if not vec_items:
        return None, None
    try:
        import numpy as np
    except Exception:
        log.info("numpy недоступен — остаётся лексический поиск")
        return None, None

    dim = len(vec_items[0]["vec"])
    vec_items = [it for it in vec_items if len(it["vec"]) == dim]
    matrix = np.asarray([it["vec"] for it in vec_items], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix /= norms

    with _lock:
        _items_cache["matrix"] = (vec_items, matrix)
    return vec_items, matrix


def _vector_hits(query: str, items: list) -> list:
    vec_items, matrix = _matrix(items)
    if not vec_items:
        return []
    qv = embed_cached(query, kind="query")
    if not qv or len(qv) != matrix.shape[1]:
        return []
    try:
        import numpy as np
        qa = np.asarray(qv, dtype=np.float32)
        qa = qa / (float(np.linalg.norm(qa)) + 1e-9)
        sims = matrix @ qa
    except Exception:
        log.exception("Векторный поиск упал")
        return []
    return [(float(sims[i]), vec_items[i]) for i in range(len(vec_items))]


def search(query: str, k: int = 3, min_score: float = None,
           lexical_min: float = None) -> list:
    """Ищет факты по смыслу. Работает и без эмбеддингов (лексика).

    Два порога, потому что шкалы разные: косинус у nomic сжат в 0.57–0.74,
    а лексическая близость разбросана шире. Один порог на оба пути либо
    пропускал бы мусор, либо отсекал годное.

    Возвращает [{"key", "value", "score"}] — отсортировано по убыванию.
    """
    q = (query or "").strip()
    if not q:
        return []
    try:
        k = max(1, int(k or 3))
    except (TypeError, ValueError):
        k = 3
    v_th = _min_score() if min_score is None else float(min_score)
    l_th = _lexical_min() if lexical_min is None else float(lexical_min)

    items = _items() or _items_from_facts()
    if not items:
        return []

    hits = [(s, it) for s, it in _vector_hits(q, items) if s >= v_th]
    if hits:
        # Факты без вектора (только что добавлен, фон не успел) — добираем лексикой.
        seen = {id(it) for _, it in hits}
        hits += [(s, it) for s, it in _lexical_hits(q, items)
                 if id(it) not in seen and s >= l_th]
    elif _lexical_fallback():
        hits = [(s, it) for s, it in _lexical_hits(q, items) if s >= l_th]

    if not hits:
        return []
    hits.sort(key=lambda pair: pair[0], reverse=True)
    return [{"key": it.get("key", ""), "value": it.get("value", ""), "score": score}
            for score, it in hits[:k]]


def _confident(hits: list) -> bool:
    """Есть ли явный лидер?

    Одинокому хиту сравнивать не с чем, поэтому с него спрос строже:
    порог плюс отрыв (0.64 против 0.6). Иначе случайный факт на запрос
    «сколько сейчас времени» (0.626) проходил бы как «явный победитель» —
    ровно на этом живой замер 14.10.2026 и поймал фичу.
    """
    if not hits:
        return False
    if len(hits) == 1:
        return hits[0]["score"] >= _min_score() + _margin()
    return (hits[0]["score"] - hits[1]["score"]) >= _margin()


def build_prompt_block(query: str, k: int = None) -> str:
    """Блок фактов для system-промпта. "" — если отбирать нечего или не уверены.

    Пустая строка означает «добавь все факты как раньше» (learning.build_context).
    """
    if not _enabled():
        return ""
    q = (query or "").strip()
    if not q:
        return ""
    facts = _facts()
    if not facts:
        return ""
    k = _top_k() if k is None else max(1, int(k))
    if len(facts) <= k:
        # Отбирать не из чего — brain возьмёт все факты.
        return ""

    hits = search(q, k=k)
    if not hits:
        return ""
    if not _confident(hits):
        # Явного победителя нет — не рискуем: пусть brain возьмёт все факты.
        return ""
    lines = [f"- {h['key']}: {h['value']}" for h in hits]
    return ("Факты о пользователе (отобраны по смыслу запроса):\n"
            + "\n".join(lines) + "\n")


# ---------------------------------------------------------------
# Сверка индекса с профилем + фоновый воркер
# ---------------------------------------------------------------

def _round_vec(vec) -> list:
    try:
        return [round(float(x), 6) for x in vec]
    except Exception:
        return []


def sync(force: bool = False) -> int:
    """Сверяет индекс с profile.json. Возвращает число изменений.

    Вызывается фоном; на горячем пути диалога никогда не выполняется.
    """
    if not _enabled():
        return 0
    path = index_path()
    facts = _facts()

    data = {} if force else load_index()
    items = {}
    for it in data.get("items", []):
        key = it.get("key")
        if key and it.get("value") == facts.get(key):
            items[key] = it

    missing = [(k, v) for k, v in facts.items() if k not in items]

    # Считаем каждый факт один раз: правка значения — это одно изменение,
    # а не «удалили + добавили».
    old_keys = {it.get("key") for it in data.get("items", [])}
    changed = len(old_keys - set(items) - {k for k, _ in missing})
    if missing:
        try:
            max_items = max(1, int(_cfg("memory_rag_max_items", 500) or 500))
        except (TypeError, ValueError):
            max_items = 500
        missing = missing[:max(0, max_items - len(items))]

        texts = [f"{k}: {v}" for k, v in missing]
        # В фоне таймаут щедрее: голосовой цикл здесь не ждёт,
        # а первый вызов грузит модель (~20 с на живых замерах).
        vecs = embed_texts(texts, kind="document", timeout=_background_timeout())
        for (key, value), vec in zip(missing, vecs or []):
            if not vec:
                continue
            items[key] = {
                "key": key,
                "value": value,
                "text": f"{key}: {value}",
                "vec": _round_vec(vec),
                "ts": time.time(),
                "src": "user",
            }
            changed += 1

    if changed:
        if index_path() != path:
            # Профиль переключился, пока считали — в чужой индекс не пишем.
            log.info("Профиль сменился во время индексации — пропускаю запись")
            _invalidate()
            return 0
        dim = int(data.get("dim", 0) or 0)
        for it in items.values():
            if it.get("vec"):
                dim = len(it["vec"])
                break
        if not save_index(list(items.values()), dim):
            return 0
        _invalidate()

    return changed


def index_fact(key: str, value: str, source: str = "user") -> None:
    """Хук learning.add_fact: будим воркер (сам факт уже в profile.json)."""
    if not _enabled():
        return
    _wake.set()
    if _worker is None or not _worker.is_alive():
        warmup_async()


def forget_fact(key: str) -> None:
    """Хук learning.forget_fact: индекс почистит sync."""
    index_fact(key, "")


def warmup_async() -> None:
    """Запускает фоновую сборку индекса (демон-поток)."""
    global _worker
    if not _enabled():
        return
    with _lock:
        if _worker is not None and _worker.is_alive():
            _wake.set()
            return
        _stop.clear()
        _wake.set()
        _worker = threading.Thread(target=_worker_loop,
                                   name="vectormem-index", daemon=True)
        _worker.start()
        log.info("Индексация фактов запущена в фоне")


def _warm_embed() -> None:
    """Один пробный эмбеддинг — грузит модель в память заранее.

    Иначе первый же вопрос пользователя упирался бы в холодный старт
    модели (а это дольше таймаута горячего пути), и Феникс молча отвечал
    бы по словам вместо смысла. Заодно рано видно, что модель не скачана.
    """
    if embed_texts(["прогрев"], kind="query",
                   timeout=_background_timeout()) is None:
        log.info("Эмбеддинги недоступны — пока ищем по словам, "
                 "не по смыслу (нужна «ollama pull %s»)", _model())


def _worker_loop() -> None:
    _warm_embed()
    while not _stop.is_set():
        _wake.wait(timeout=5.0)
        _wake.clear()
        if _stop.is_set():
            break
        try:
            sync()
        except Exception:
            log.exception("vectormem.sync упал")


def stop() -> None:
    """Останавливает воркер (на выходе приложения)."""
    _stop.set()
    _wake.set()


def on_config_change(key: str, value) -> None:
    """Реакция на смену настроек в рантайме."""
    global _legacy_api, _fails, _breaker_until
    if key == "ollama_url":
        _legacy_api = False
        _invalidate()
        return
    if key in ("memory_rag_enabled", "memory_rag_model"):
        _legacy_api = False
        _fails = 0
        _breaker_until = 0.0
        with _lock:
            _embed_cache.clear()
        _invalidate()
        if value:
            warmup_async()


def status() -> dict:
    """Состояние для GUI и команд «какая память»."""
    items = _items()
    return {
        "enabled": _enabled(),
        "model": _model(),
        "items": len(items),
        "vectors": sum(1 for it in items if it.get("vec")),
        "breaker": time.time() < _breaker_until,
        "legacy_api": _legacy_api,
        "path": str(index_path()),
    }


def reset_for_tests() -> None:
    """Сброс кэшей между тестами."""
    global _fails, _breaker_until, _legacy_api, _said_no_model
    with _lock:
        _embed_cache.clear()
        _items_cache["stamp"] = None
        _items_cache["items"] = []
        _items_cache["matrix"] = None
    _fails = 0
    _breaker_until = 0.0
    _legacy_api = False
    _said_no_model = False
