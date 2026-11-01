"""Каталог движков: статусы по файлам/пакетам и установка через явный вызов.

Сети нет: httpx/urllib подменяются фейками. Проверяется то, что видит человек
на вкладке «Движки», — скачано/нет, активно/нет и что делает кнопка.
"""

import json

import pytest

from jarvis import engines, paths
from jarvis import model as vosk_model

FAKE_OLLAMA = object()


class FakeResponse:
    def __init__(self, payload=b"", lines=None):
        self._payload = payload
        self._lines = list(lines or [])

    def read(self, limit=None):
        return self._payload if limit is None else self._payload[:limit]

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.urls = []

    def open(self, request, timeout=None):
        self.urls.append(getattr(request, "full_url", request))
        return self.response


def fake_ollama(monkeypatch, response):
    opener = FakeOpener(response)
    monkeypatch.setattr(engines, "_ollama_opener", lambda: opener)
    return opener


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """Свои каталоги: ни реальных моделей, ни реального конфига."""
    monkeypatch.setattr(paths, "program_models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(paths, "program_whisper_cache_dir", lambda: tmp_path / "whisper")
    monkeypatch.setattr(paths, "program_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "user_dir", lambda: tmp_path)
    (tmp_path / "models").mkdir()
    (tmp_path / "whisper").mkdir()
    return tmp_path


class Config(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

@pytest.fixture(autouse=True)
def packages_present(monkeypatch):
    """Пакеты движков считаются установленными, независимо от машины.

    В CI ставится только requirements-ci.txt: vosk, faster-whisper, piper и
    torch там отсутствуют. Без этой подмены статусы «скачано/нет» зависели от
    того, что стоит у разработчика: локально зелено, в CI красно (поймано на
    прогоне 41333131841). Отсутствие пакета проверяется отдельным тестом
    test_whisper_reports_missing_package — он перекрывает подмену на False.
    """
    monkeypatch.setattr(engines, "_package", lambda name: True)


def test_catalog_lists_every_group_and_engine(tree):
    items = engines.catalog(Config())
    keys = [item.key for item in items]
    assert keys == ["vad", "vosk", "whisper", "piper", "silero", "sapi", "ollama", "cloud"]
    assert {item.group for item in items} == {engines.GROUP_STT, engines.GROUP_TTS,
                                              engines.GROUP_LLM}


def test_vosk_requires_package_and_required_files(tree):
    info = engines.vosk_info(Config())
    assert not info.installed and "не скачана" in info.detail
    ready = tree / "models" / vosk_model.MODEL_NAME
    for rel in vosk_model.REQUIRED_MODEL_FILES:
        target = ready / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    info = engines.vosk_info(Config())
    assert info.installed and info.active
    assert vosk_model.MODEL_NAME in info.detail


def test_whisper_status_follows_cache_and_use_flag(tree):
    assert not engines.whisper_info(Config()).installed
    folder = engines.whisper_cache_model_dir(Config({"whisper_model": "org/model"}))
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(b"x" * 10)
    cached = engines.whisper_info(Config({"whisper_model": "org/model"}))
    assert cached.installed and cached.active
    assert "org/model" in cached.detail
    off = engines.whisper_info(Config({"whisper_model": "org/model", "use_whisper": False}))
    assert off.installed and not off.active


def test_whisper_reports_missing_package(tree, monkeypatch):
    monkeypatch.setattr(engines, "_package", lambda name: False)
    info = engines.whisper_info(Config())
    assert not info.installed and "пакета" in info.detail.lower()
    # Пакет из окна не поставить: кнопка не должна обещать скачивание модели.
    assert info.installable is False
    assert "pip" in info.hint


def test_vad_status_uses_found_file(tree, monkeypatch):
    assert not engines.vad_info(Config()).installed
    onnx = tree / "vad" / "silero_vad.onnx"
    onnx.parent.mkdir()
    onnx.write_bytes(b"x" * 2048)
    monkeypatch.setattr(engines, "vad_model_path", lambda: onnx)
    info = engines.vad_info(Config({"vad_enabled": False}))
    assert info.installed and not info.active
    assert "silero_vad.onnx" in info.detail


def test_tts_active_follows_config_and_availability(tree, monkeypatch):
    monkeypatch.setattr(engines, "_tts_available", lambda: ["sapi"])
    assert engines.active_tts_engine(Config()) == "sapi"
    assert engines.sapi_info(Config()).active
    monkeypatch.setattr(engines, "_tts_available", lambda: ["silero", "piper", "sapi"])
    assert engines.active_tts_engine(Config({"tts_backend": "piper"})) == "piper"
    assert engines.active_tts_engine(Config({"tts_backend": "auto"})) == "silero"
    assert engines.active_tts_engine(Config({"tts_backend": "sapi"})) == "sapi"
    monkeypatch.setattr(engines, "_tts_available", lambda: [])
    assert engines.active_tts_engine(Config()) == ""


def test_piper_cached_only_when_model_and_config_present(tree, monkeypatch):
    seen = {}

    def cache(repo, rel):
        seen["repo"] = repo
        return "/cache/model.onnx" if rel.endswith(".onnx") else "/cache/model.onnx.json"

    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub",
                        type("M", (), {"try_to_load_from_cache": staticmethod(cache)}))
    info = engines.piper_info(Config({"tts_voice": "irina"}))
    assert info.installed
    assert "irina" in info.detail
    assert seen["repo"] == "rhasspy/piper-voices"


def test_ollama_status_needs_server_and_model(tree, monkeypatch):
    info = engines.ollama_info(Config())
    assert not info.installed
    assert "не отвечает" in info.detail
    names = ["qwen2.5:7b-instruct"]
    info = engines.ollama_info(Config(), names=names)
    assert info.installed and info.active
    other = engines.ollama_info(Config({"llm_model": "gemma2:9b"}), names=names)
    assert not other.installed and "gemma2:9b" in other.detail
    cloud = engines.ollama_info(Config({"cloud_enabled": True}), names=names)
    assert cloud.installed and not cloud.active


def test_cloud_status_needs_key_and_switch(tree, monkeypatch):
    info = engines.cloud_info(Config({"cloud_enabled": True}))
    assert not info.installed and "ключа нет" in info.detail
    monkeypatch.setattr(engines, "secrets_store", None, raising=False)
    import jarvis.secrets_store as store

    monkeypatch.setattr(store, "has_secret", lambda name: True)
    info = engines.cloud_info(Config({"cloud_enabled": True, "cloud_provider": "deepseek",
                                      "cloud_model": "deepseek-chat"}))
    assert info.installed and info.active
    assert "deepseek: deepseek-chat" in info.detail


def test_local_only_ollama_addresses(tree):
    assert engines._local_ollama_url("http://127.0.0.1:11434")
    assert engines._local_ollama_url("http://localhost:11434")
    assert not engines._local_ollama_url("https://ollama.example.com")
    assert not engines._local_ollama_url("ftp://127.0.0.1:11434")


def test_ollama_inventory_parses_names_and_survives_garbage(tree, monkeypatch):
    fake_ollama(monkeypatch, FakeResponse(json.dumps(
        {"models": [{"name": "a:1"}, {"name": ""}, "str", {"name": "b:2"}]}).encode()))
    assert engines.ollama_inventory("http://127.0.0.1:11434") == ["a:1", "b:2"]
    fake_ollama(monkeypatch, FakeResponse("не json".encode()))
    assert engines.ollama_inventory("http://127.0.0.1:11434") == []


def test_ollama_pull_reports_progress_and_errors(tree, monkeypatch):
    lines = [
        json.dumps({"status": "pulling", "total": 100, "completed": 50}).encode() + b"\n",
        json.dumps({"status": "pulling", "total": 100, "completed": 100}).encode() + b"\n",
    ]
    fake_ollama(monkeypatch, FakeResponse(lines=lines))
    seen = []
    ok, message = engines.install("ollama", lambda f, m: seen.append((f, m)),
                                  Config({"llm_model": "qwen2.5:7b-instruct"}))
    assert ok and "скачана" in message
    fractions = [f for f, _ in seen if f is not None]
    assert fractions[0] == 0.0 and fractions[-1] == 1.0
    assert 0.5 in fractions
    assert fractions == sorted(fractions)  # прогресс не откатывается назад
    fake_ollama(monkeypatch, FakeResponse(
        lines=[json.dumps({"error": "boom"}).encode() + b"\n"]))
    ok, message = engines.install("ollama", lambda f, m: None, Config())
    assert not ok and "boom" in message


def test_ollama_pull_refuses_remote_address(tree):
    ok, message = engines.install("ollama", lambda f, m: None,
                                  Config({"ollama_url": "https://evil.example"}))
    assert not ok and "локальным" in message


def test_install_reports_missing_network_without_traceback(tree, monkeypatch):
    monkeypatch.setattr(engines, "vad_model_path", lambda: None)
    from jarvis import vad

    monkeypatch.setattr(vad, "download_model", lambda dest=None: None)
    ok, message = engines.install("vad", lambda f, m: None)
    assert not ok and "интернет" in message


def test_install_runs_engine_and_reports_success(tree, monkeypatch):
    from jarvis import vad

    target = tree / "vad" / "silero_vad.onnx"
    target.parent.mkdir()
    target.write_bytes(b"x" * 1024)
    monkeypatch.setattr(vad, "download_model", lambda dest=None: target)
    seen = []
    ok, message = engines.install("vad", lambda f, m: seen.append(f))
    assert ok and "silero_vad.onnx" in message
    assert seen[0] == 0.0 and seen[-1] == 1.0


def test_install_refuses_unknown_or_system_engine(tree):
    ok, message = engines.install("sapi", lambda f, m: None)
    assert not ok and "системный" in message
    ok, message = engines.install("no-such-engine", lambda f, m: None)
    assert not ok
