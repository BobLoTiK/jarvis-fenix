"""Векторная память фактов (jarvis.vectormem, №51–53).

Фича подбирает нужные факты о пользователе по смыслу запроса вместо
«все факты всегда». Эмбеддинги считает локальная Ollama; здесь сети нет —
urllib подменён заглушкой, а размерности и векторы задаются вручную.

Проверяем:
    - по умолчанию выключено и НИ ОДНОГО сетевого вызова;
    - sync(): добавляет факты, убирает исчезнувшие, переживает битый файл;
    - поиск: ранг по косинусу, порог, правило «фактов ≤ k — не отбираем»;
    - смена модели инвалидирует индекс целиком (векторы несравнимы);
    - без эмбеддингов — лексический фолбэк, а если и он не уверен — пусто;
    - префиксы search_document/search_query только для nomic;
    - 404 от Ollama: «модель не скачана» отличается от «нет эндпоинта»;
    - предохранитель после трёх ошибок и 10 потоков на запись индекса.
"""

import io
import json
import threading
import urllib.error

import pytest

from jarvis import learning, profile, vectormem
from jarvis.config import Config


# ---------------------------------------------------------------
# Инфраструктура тестов
# ---------------------------------------------------------------

class _Resp(io.BytesIO):
    """Заглушка ответа urlopen (контекстный менеджер, как у настоящего)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _never_called(*args, **kwargs):  # pragma: no cover - защита от вызова
    raise AssertionError("сетевой вызов, которого быть не должно")


class FakeOllama:
    """Подменяет urlopen: отвечает на /api/embed по таблице векторов."""

    def __init__(self, table=None, dim=4, fail=None):
        self.table = table or {}
        self.dim = dim
        self.fail = fail
        self.calls = []          # [(url, payload)]

    def __call__(self, request, timeout=None):
        url = request.full_url
        payload = json.loads(request.data.decode("utf-8"))
        self.calls.append((url, payload))
        if self.fail is not None:
            raise self.fail
        if url.endswith("/api/embed"):
            vecs = [self.table.get(t, [0.0] * self.dim) for t in payload["input"]]
            return _Resp(json.dumps({"embeddings": vecs}).encode("utf-8"))
        if url.endswith("/api/embeddings"):
            vec = self.table.get(payload["prompt"], [0.0] * self.dim)
            return _Resp(json.dumps({"embedding": vec}).encode("utf-8"))
        raise AssertionError(f"неожиданный URL: {url}")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Свой профиль на тест: реальные facts пользователя не трогаем."""
    monkeypatch.setattr(profile, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(vectormem, "_config", None)
    # Фоновый воркер в тестах не нужен: sync() зовём вручную.
    monkeypatch.setattr(vectormem, "warmup_async", lambda: None)
    profile._cache_invalidate()
    vectormem.reset_for_tests()
    yield
    vectormem.reset_for_tests()
    profile._cache_invalidate()


@pytest.fixture()
def cfg(tmp_path):
    """Изолированный конфиг с включённой векторной памятью."""
    c = Config(tmp_path / "config.json")
    c.set("memory_rag_enabled", True)
    vectormem.set_config(c)
    return c


def _vectors():
    """Таблица «текст → вектор» для предсказуемых косинусов."""
    return {
        "search_document: город: Казань": [1.0, 0.0, 0.0, 0.0],
        "search_document: работа: программист": [0.0, 1.0, 0.0, 0.0],
        "search_document: любимая игра: Дота": [0.0, 0.0, 1.0, 0.0],
        "search_document: любимый фильм: Матрица": [0.0, 0.0, 0.0, 1.0],
        "search_query: какой у меня город": [1.0, 0.0, 0.0, 0.0],
        "search_query: во что я играю": [0.0, 0.0, 1.0, 0.0],
    }


def _seed(tmp_path, monkeypatch, table=None):
    """Кладёт 4 факта и подменяет urlopen. Возвращает заглушку."""
    fake = FakeOllama(table=table if table is not None else _vectors())
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", fake)
    for key, value in (("город", "Казань"), ("работа", "программист"),
                       ("любимая игра", "Дота"), ("любимый фильм", "Матрица")):
        assert learning.add_fact(key, value)
    return fake


# ---------------------------------------------------------------
# Выключено по умолчанию
# ---------------------------------------------------------------

def test_disabled_by_default_makes_no_calls(tmp_path, monkeypatch):
    """Фича выключена — ни одного сетевого вызова и никакого блока в промпт."""
    c = Config(tmp_path / "config.json")
    vectormem.set_config(c)
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", _never_called)

    learning.add_fact("город", "Казань")

    assert vectormem.build_prompt_block("какой у меня город") == ""
    assert vectormem.sync() == 0
    assert vectormem.index_fact("город", "Казань") is None


# ---------------------------------------------------------------
# Индексация
# ---------------------------------------------------------------

def test_sync_indexes_facts(cfg, tmp_path, monkeypatch):
    fake = _seed(tmp_path, monkeypatch)

    changed = vectormem.sync()

    assert changed == 4
    data = json.loads(profile.memory_index_path().read_text(encoding="utf-8"))
    assert data["embed_model"] == "nomic-embed-text"
    assert data["dim"] == 4
    assert {it["key"] for it in data["items"]} == {
        "город", "работа", "любимая игра", "любимый фильм"}
    assert all(len(it["vec"]) == 4 for it in data["items"])
    assert len(fake.calls) == 1                      # один батч, не четыре вызова
    assert len(fake.calls[0][1]["input"]) == 4


def test_sync_is_idempotent(cfg, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert vectormem.sync() == 4
    assert vectormem.sync() == 0


def test_sync_removes_orphans(cfg, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    vectormem.sync()

    assert learning.forget_fact("город")
    assert vectormem.sync() == 1

    data = json.loads(profile.memory_index_path().read_text(encoding="utf-8"))
    assert "город" not in {it["key"] for it in data["items"]}


def test_sync_updates_changed_value(cfg, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    vectormem.sync()

    assert learning.add_fact("город", "Москва")
    assert vectormem.sync() == 1

    data = json.loads(profile.memory_index_path().read_text(encoding="utf-8"))
    item = next(it for it in data["items"] if it["key"] == "город")
    assert item["value"] == "Москва"


def test_model_change_invalidates_index(cfg, tmp_path, monkeypatch):
    """Векторы разных моделей несравнимы — индекс пересобирается целиком."""
    _seed(tmp_path, monkeypatch)
    vectormem.sync()
    assert vectormem.status()["items"] == 4

    cfg.set("memory_rag_model", "bge-m3")

    assert vectormem.load_index() == {}
    assert vectormem.status()["items"] == 0


def test_broken_index_file(cfg, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    profile.memory_index_path().write_text("{это не json", encoding="utf-8")

    assert vectormem.load_index() == {}
    assert vectormem.status()["items"] == 0
    # Факты — источник правды, поиск продолжает работать (лексика).
    assert vectormem.search("какой у меня город")[0]["key"] == "город"


# ---------------------------------------------------------------
# Поиск и блок промпта
# ---------------------------------------------------------------

def test_search_ranks_by_cosine(cfg, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    vectormem.sync()

    hits = vectormem.search("во что я играю")

    assert hits[0]["key"] == "любимая игра"
    assert hits[0]["score"] == pytest.approx(1.0)
    assert all(h["score"] < 0.5 for h in hits[1:])


def test_search_respects_threshold(cfg, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    vectormem.sync()

    # Ни одно слово не пересекается с фактами — лучше промолчать.
    assert vectormem.search("сколько сейчас времени в космосе") == []


def test_prompt_block_skips_selection_for_few_facts(cfg, tmp_path, monkeypatch):
    """Фактов ≤ k — отбирать не из чего: блок пуст, brain возьмёт все."""
    fake = FakeOllama(table=_vectors())
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", fake)
    learning.add_fact("город", "Казань")
    learning.add_fact("работа", "программист")
    learning.add_fact("любимая игра", "Дота")

    assert vectormem.build_prompt_block("какой у меня город") == ""
    assert fake.calls == []


def test_prompt_block_selects_relevant_facts(cfg, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    vectormem.sync()

    block = vectormem.build_prompt_block("какой у меня город")

    assert "Казань" in block
    assert "Матрица" not in block          # нерелевантное не подмешиваем


def test_prompt_block_empty_query(cfg, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    vectormem.sync()

    assert vectormem.build_prompt_block("") == ""
    assert vectormem.build_prompt_block(None) == ""


# ---------------------------------------------------------------
# Деградация
# ---------------------------------------------------------------

def test_lexical_fallback_without_embeddings(cfg, tmp_path, monkeypatch):
    """Ollama недоступна — ищем по словам, а не молчим."""
    fake = FakeOllama(table=_vectors(), fail=urllib.error.URLError("нет сети"))
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", fake)
    for key, value in (("город", "Казань"), ("работа", "программист"),
                       ("любимая игра", "Дота"), ("любимый фильм", "Матрица")):
        learning.add_fact(key, value)

    hits = vectormem.search("какой у меня город")

    assert hits and hits[0]["key"] == "город"


def test_lexical_fallback_can_be_disabled(cfg, tmp_path, monkeypatch):
    cfg.set("memory_rag_lexical_fallback", False)
    fake = FakeOllama(table=_vectors(), fail=urllib.error.URLError("нет сети"))
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", fake)
    learning.add_fact("город", "Казань")
    learning.add_fact("работа", "программист")

    assert vectormem.search("какой у меня город") == []


def test_breaker_stops_hammering_ollama(cfg, tmp_path, monkeypatch):
    """Три ошибки подряд — пауза: недоступная модель не тормозит диалог."""
    fake = FakeOllama(fail=urllib.error.URLError("нет сети"))
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", fake)

    for _ in range(3):
        assert vectormem.embed_texts(["текст"]) is None
    assert len(fake.calls) == 3
    assert vectormem.status()["breaker"] is True

    assert vectormem.embed_texts(["текст"]) is None
    assert len(fake.calls) == 3                    # в сеть больше не ходили


def test_breaker_resets_on_success(cfg, tmp_path, monkeypatch):
    fake = FakeOllama(fail=urllib.error.URLError("нет сети"))
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", fake)
    for _ in range(2):
        vectormem.embed_texts(["текст"])

    good = FakeOllama(table={"search_document: текст": [1.0, 0.0]})
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", good)
    assert vectormem.embed_texts(["текст"]) == [[1.0, 0.0]]

    assert vectormem.status()["breaker"] is False


def test_missing_model_warns_and_does_not_switch_endpoint(cfg, tmp_path, monkeypatch):
    """404 «модель не скачана» — это не «старый Ollama без /api/embed»."""
    body = io.BytesIO(json.dumps(
        {"error": 'model "nomic-embed-text" not found, try pulling it first'}
    ).encode("utf-8"))
    err = urllib.error.HTTPError("http://127.0.0.1:11434/api/embed", 404,
                                 "Not Found", {}, body)
    fake = FakeOllama(fail=err)
    monkeypatch.setattr(vectormem.urllib.request, "urlopen", fake)

    assert vectormem.embed_texts(["текст"]) is None
    assert vectormem.status()["legacy_api"] is False
    assert [c[0] for c in fake.calls] == ["http://127.0.0.1:11434/api/embed"]


def test_old_ollama_falls_back_to_legacy_endpoint(cfg, tmp_path, monkeypatch):
    """Ollama без /api/embed (404 на маршрут) — переходим на /api/embeddings."""
    body = io.BytesIO(b"404 page not found")
    err = urllib.error.HTTPError("http://127.0.0.1:11434/api/embed", 404,
                                 "Not Found", {}, body)

    urls = []

    class _Mixed:
        def __call__(self, request, timeout=None):
            urls.append(request.full_url)
            if request.full_url.endswith("/api/embed"):
                raise err
            return _Resp(json.dumps({"embedding": [0.5, 0.5]}).encode("utf-8"))

    monkeypatch.setattr(vectormem.urllib.request, "urlopen", _Mixed())

    assert vectormem.embed_texts(["текст"]) == [[0.5, 0.5]]
    assert urls == ["http://127.0.0.1:11434/api/embed",
                    "http://127.0.0.1:11434/api/embeddings"]
    assert vectormem.status()["legacy_api"] is True


def test_prefixes_only_for_nomic(cfg, tmp_path, monkeypatch):
    """У nomic запрос и документ — разные префиксы; у bge их быть не должно."""
    cfg.set("memory_rag_model", "nomic-embed-text")
    assert vectormem._apply_prefix("привет", "document").startswith("search_document: ")
    assert vectormem._apply_prefix("привет", "query").startswith("search_query: ")

    cfg.set("memory_rag_model", "bge-m3")
    assert vectormem._apply_prefix("привет", "document") == "привет"
    assert vectormem._apply_prefix("привет", "query") == "привет"


# ---------------------------------------------------------------
# Потоки
# ---------------------------------------------------------------

def test_concurrent_sync_keeps_index_valid(cfg, tmp_path, monkeypatch):
    """10 потоков пишут индекс — файл остаётся целым, дублей нет."""
    _seed(tmp_path, monkeypatch)
    vectormem.sync()

    errors = []

    def _work():
        try:
            vectormem.sync()
            vectormem.search("какой у меня город")
        except Exception as e:                       # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=_work) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    data = json.loads(profile.memory_index_path().read_text(encoding="utf-8"))
    keys = [it["key"] for it in data["items"]]
    assert sorted(keys) == sorted(set(keys))
    assert len(keys) == 4
