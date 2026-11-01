"""Каталог движков Феникса: что скачано, что включено и чем доустановить.

Модуль без Flet: перечисление статусов и установка живут здесь, а рисует их
вкладка «Движки». Сеть трогается только в двух случаях —

* `ollama_inventory` — короткий GET /api/tags, его вкладка зовёт из фонового
  потока (не при построении экрана);
* `install` — явное действие пользователя по кнопке.

Ни один статус не запускает скачивание сам по себе: автозагрузка моделей
осталась в тех местах, где была (VAD при старте по `vad_auto_download`,
Whisper при первом распознавании, Piper/Silero при первом синтезе).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jarvis import paths

log = logging.getLogger("jarvis.engines")

GROUP_STT = "Распознавание речи"
GROUP_TTS = "Синтез речи"
GROUP_LLM = "Языковые модели"

# progress(доля 0..1 или None, что происходит) — None означает «размер неизвестен».
Progress = Callable[[float | None, str], None]

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class EngineInfo:
    """Одна строка каталога. installed — файлы/пакет на месте, active — по конфигу."""

    key: str
    group: str
    title: str
    description: str
    installed: bool
    active: bool
    detail: str = ""
    installable: bool = True
    install_label: str = "Установить"
    package: str | None = None
    size_hint: str = ""
    hint: str = ""


class EngineError(RuntimeError):
    """Установка не удалась. Текст безопасен для показа в интерфейсе."""


# --- дешёвые проверки -------------------------------------------------------


def _package(name: str | None) -> bool:
    if not name:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _dir_size(path: Path, *, limit: int = 4000) -> int:
    """Размер каталога без зависания на гигантских деревьях."""
    total = 0
    seen = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
            seen += 1
            if seen > limit:
                break
    except OSError:
        return total
    return total


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.0f} МБ"


def _model_name(config=None) -> str:
    value = None
    if config is not None:
        try:
            value = config.get("whisper_model")
        except Exception:
            value = None
    return str(value or "deepdml/faster-whisper-large-v3-turbo-ct2")


def whisper_cache_dir() -> Path:
    return paths.program_whisper_cache_dir()


def whisper_cache_model_dir(config=None) -> Path:
    """Куда huggingface_hub кладёт snapshot выбранной модели."""
    return whisper_cache_dir() / ("models--" + _model_name(config).replace("/", "--"))


def whisper_cache_has_model(config=None) -> bool:
    return whisper_cache_model_dir(config).is_dir()


def piper_voice(config=None) -> tuple[str, str]:
    voice, quality = "ruslan", "medium"
    if config is not None:
        try:
            voice = str(config.get("tts_voice") or voice)
            quality = str(config.get("tts_voice_quality") or quality)
        except Exception:
            pass
    return voice, (quality if quality in ("medium", "high") else "medium")


def piper_voice_cached(config=None) -> bool:
    """Есть ли .onnx выбранного голоса в кэше HF (без сети и без загрузки модели)."""
    voice, quality = piper_voice(config)
    rel = f"ru/ru_RU/{voice}/{quality}/ru_RU-{voice}-{quality}.onnx"
    try:
        from huggingface_hub import try_to_load_from_cache

        from jarvis.tts_engines.piper import PIPER_REPO

        cached = try_to_load_from_cache(PIPER_REPO, rel)
        if not isinstance(cached, str):
            return False
        # Рядом с .onnx нужен конфиг: без него PiperVoice.load не поднимется.
        return isinstance(try_to_load_from_cache(PIPER_REPO, rel + ".json"), str)
    except Exception:
        return False


def silero_hub_dir() -> Path:
    """torch.hub держит клон snakers4/silero-models внутри TORCH_HOME."""
    return paths.program_dir() / "torch" / "hub" / "snakers4_silero-models_master"


def silero_cached() -> bool:
    return _package("torch") and silero_hub_dir().is_dir()


def vosk_model_dir() -> Path:
    from jarvis import model as vosk_model

    return paths.program_models_dir() / vosk_model.MODEL_NAME


def vosk_ready() -> bool:
    from jarvis import model as vosk_model

    return vosk_model.model_is_ready(vosk_model_dir())


def vad_model_path() -> Path | None:
    from jarvis import vad

    try:
        return vad.find_model()
    except Exception:
        return None


def _tts_available() -> list[str]:
    try:
        from jarvis.tts_engines.factory import list_engines

        return list_engines()
    except Exception:
        log.debug("engines: список TTS-движков недоступен", exc_info=True)
        return []


def active_tts_engine(config=None) -> str:
    """Какой движок реально озвучит ответ при текущих настройках."""
    backend = "auto"
    if config is not None:
        try:
            backend = str(config.get("tts_backend") or "auto")
        except Exception:
            backend = "auto"
    available = _tts_available()
    if backend != "auto" and backend in available:
        return backend
    for name in ("silero", "piper", "sapi"):
        if name in available:
            return name
    return ""


# --- статусы ---------------------------------------------------------------


def vad_info(config=None) -> EngineInfo:
    path = vad_model_path()
    enabled = True
    if config is not None:
        try:
            enabled = bool(config.get("vad_enabled", True))
        except Exception:
            enabled = True
    if path is not None:
        try:
            size = path.stat().st_size if path.is_file() else 0
        except OSError:
            size = 0
        return EngineInfo(
            "vad", GROUP_STT, "Silero VAD",
            "Отсекает тишину до распознавания, убирает ложные фразы.",
            True, enabled, f"Файл: {path.name} ({_mb(size)})",
            size_hint="≈2,3 МБ")
    return EngineInfo(
        "vad", GROUP_STT, "Silero VAD",
        "Отсекает тишину до распознавания, убирает ложные фразы.",
        False, False, "Модели нет: VAD работает без фильтра тишины.",
        size_hint="≈2,3 МБ")


def vosk_info(config=None) -> EngineInfo:
    has_package = _package("vosk")
    ready = has_package and vosk_ready()
    detail = (f"Модель: {vosk_model_dir().name} ({_mb(_dir_size(vosk_model_dir()))})"
              if ready else ("Пакета vosk нет." if not has_package else "Модель не скачана."))
    return EngineInfo(
        "vosk", GROUP_STT, "Vosk (small ru)",
        "Основное распознавание, работает офлайн и на слабом железе.",
        ready, has_package, detail, package="vosk", size_hint="≈45 МБ",
        install_label="Скачать модель", installable=has_package,
        hint="Пакет vosk ставится через pip, не из этого окна.")


def whisper_info(config=None) -> EngineInfo:
    has_package = _package("faster_whisper")
    cached = has_package and whisper_cache_has_model(config)
    use = True
    if config is not None:
        try:
            use = bool(config.get("use_whisper", True))
        except Exception:
            use = True
    if cached:
        folder = whisper_cache_model_dir(config)
        detail = f"Модель: {_model_name(config)} ({_mb(_dir_size(folder))})"
    elif not has_package:
        detail = "Пакета faster-whisper нет."
    else:
        detail = f"Модель {_model_name(config)} не скачана."
    return EngineInfo(
        "whisper", GROUP_STT, "Faster-Whisper",
        "Точнее Vosk на сложной речи; модель крупная, первый запуск дольше.",
        cached, cached and use, detail, package="faster_whisper",
        install_label="Скачать модель", installable=has_package,
        hint="Пакет faster-whisper ставится через pip, не из этого окна.")


def piper_info(config=None) -> EngineInfo:
    has_package = _package("piper")
    cached = has_package and piper_voice_cached(config)
    voice, quality = piper_voice(config)
    active = active_tts_engine(config) == "piper"
    if cached:
        detail = f"Голос: {voice}/{quality} (кэш HF)"
    else:
        detail = ("Пакета piper нет." if not has_package
                  else f"Голос {voice}/{quality} не скачан.")
    return EngineInfo(
        "piper", GROUP_TTS, "Piper",
        "Быстрый офлайн-синтез, четыре русских голоса, без GPU.",
        cached, active, detail, package="piper", size_hint="≈60 МБ",
        install_label="Скачать голос", installable=has_package,
        hint="Пакет piper ставится через pip, не из этого окна.")


def silero_info(config=None) -> EngineInfo:
    cached = silero_cached()
    active = active_tts_engine(config) == "silero"
    if cached:
        detail = f"Модель torch.hub: {_mb(_dir_size(silero_hub_dir()))}"
    elif not _package("torch"):
        detail = "Пакета torch нет."
    else:
        detail = "Модель Silero не скачана (torch.hub)."
    return EngineInfo(
        "silero", GROUP_TTS, "Silero",
        "Выразительный синтез через torch; первый запуск тянет модель.",
        cached, active, detail, package="torch", size_hint="≈150 МБ",
        install_label="Скачать модель", installable=_package("torch"),
        hint="Пакет torch ставится через pip, не из этого окна.")


def sapi_info(config=None) -> EngineInfo:
    has_package = _package("pyttsx3")
    active = active_tts_engine(config) == "sapi"
    return EngineInfo(
        "sapi", GROUP_TTS, "Windows SAPI",
        "Системный голос Windows: ничего не качает, но и не звучит как студия.",
        has_package, active,
        "Системный голос доступен." if has_package else "pyttsx3 не установлен.",
        installable=False, package="pyttsx3",
        hint="Системный голос Windows: скачивать нечего.")


def ollama_info(config=None, names: list[str] | None = None) -> EngineInfo:
    model = "qwen2.5:7b-instruct"
    url = "http://127.0.0.1:11434"
    if config is not None:
        try:
            model = str(config.get("llm_model") or model)
            url = str(config.get("ollama_url") or url)
        except Exception:
            pass
    local = _local_ollama_url(url)
    installed = bool(local) and names is not None and model in names
    if names is None:
        detail = "Сервер не отвечает: запустите Ollama, чтобы увидеть модели."
    elif not local:
        detail = "Адрес Ollama не локальный: каталог движков его не проверяет."
    elif installed:
        detail = f"Модель {model} есть в Ollama."
    else:
        detail = f"Модели {model} в Ollama нет."
    active = True
    if config is not None:
        try:
            active = (not bool(config.get("cloud_enabled", False))
                      and bool(config.get("use_llm", True)))
        except Exception:
            active = True
    return EngineInfo(
        "ollama", GROUP_LLM, "Ollama", "Локальная модель для ответов и разбора команд.",
        bool(installed), bool(installed) and active, detail,
        installable=bool(local), install_label="Скачать модель",
        hint="Сервер Ollama не локальный: каталог его не трогает.")


def cloud_info(config=None) -> EngineInfo:
    enabled = False
    provider = "openai"
    model = ""
    key = False
    if config is not None:
        try:
            enabled = bool(config.get("cloud_enabled", False))
            provider = str(config.get("cloud_provider") or provider)
            model = str(config.get("cloud_model") or "")
        except Exception:
            pass
    try:
        from jarvis import secrets_store

        key = secrets_store.has_secret(secrets_store.CLOUD_LLM_KEY)
    except Exception:
        key = False
    configured = bool(enabled and key)
    detail = ("Ответы идут в облако." if configured else
              ("Облако включено, но ключа нет." if enabled else "Облако выключено."))
    return EngineInfo(
        "cloud", GROUP_LLM, "Облачная LLM",
        "OpenAI-совместимые провайдеры и Anthropic: ничего не скачивается, нужен ключ.",
        configured, configured, f"{provider}: {model or 'модель не выбрана'}. {detail}",
        installable=False, hint="Включается и настраивается на вкладке «Облако».") 


def catalog(config=None, *, ollama_names: list[str] | None = None) -> list[EngineInfo]:
    return [
        vad_info(config), vosk_info(config), whisper_info(config),
        piper_info(config), silero_info(config), sapi_info(config),
        ollama_info(config, ollama_names), cloud_info(config),
    ]


# --- Ollama на loopback -----------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _local_ollama_url(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return ""
    if parts.scheme != "http" or (parts.hostname or "") not in _LOCAL_HOSTS:
        return ""
    return str(url).rstrip("/")


def local_ollama_url(url: str) -> str:
    """Публичная проверка «этот адрес локальный и http» для UI и тестов."""
    return _local_ollama_url(url)


def _ollama_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def ollama_inventory(url: str, *, timeout: float = 2.0) -> list[str]:
    """Имена моделей в локальной Ollama. Пустой список — сервер недоступен."""
    local = _local_ollama_url(url)
    if not local:
        return []
    try:
        with _ollama_opener().open(local + "/api/tags", timeout=timeout) as response:
            data = json.loads(response.read(1024 * 1024).decode("utf-8", "replace"))
    except Exception:
        log.debug("engines: Ollama недоступна", exc_info=True)
        return []
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    return [str(item.get("name")) for item in models
            if isinstance(item, dict) and item.get("name")]


def _ollama_pull(url: str, name: str, progress: Progress) -> tuple[bool, str]:
    local = _local_ollama_url(url)
    if not local:
        return False, "Адрес Ollama должен быть локальным (http://127.0.0.1:11434)."
    if not name:
        return False, "Сначала выберите модель в настройках LLM."
    payload = json.dumps({"model": name, "name": name, "stream": True}).encode()
    request = urllib.request.Request(
        local + "/api/pull", data=payload, headers={"Content-Type": "application/json"})
    progress(None, f"Ollama: запрашиваю {name}")
    try:
        with _ollama_opener().open(request, timeout=60) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("error"):
                    return False, f"Ollama: {event['error']}"
                total = event.get("total")
                done = event.get("completed")
                if isinstance(total, int) and total > 0 and isinstance(done, int):
                    progress(min(1.0, done / total), str(event.get("status") or "Скачивание"))
                else:
                    progress(None, str(event.get("status") or "Скачивание"))
    except Exception as error:
        return False, f"Ollama: {type(error).__name__}"
    progress(1.0, "Готово")
    return True, f"Модель {name} скачана."


# --- установка --------------------------------------------------------------


def install(key: str, progress: Progress, config=None) -> tuple[bool, str]:
    """Доустанавливает движок. Возвращает (успех, сообщение для человека)."""
    progress(0.0, "Начинаю…")
    try:
        if key == "vad":
            from jarvis import vad

            progress(None, "Скачиваю Silero VAD (~2,3 МБ)…")
            path = vad.download_model()
            if path is None:
                return False, "Не удалось скачать VAD: проверьте интернет - повторите позже."
            progress(1.0, "VAD скачан.")
            return True, f"Silero VAD на месте: {path.name}"

        if key == "vosk":
            from jarvis import model as vosk_model

            def hook(blocks, block_size, total):
                if total and total > 0:
                    progress(min(1.0, blocks * block_size / total),
                             "Скачиваю модель Vosk (~45 МБ)…")
                else:
                    progress(None, "Скачиваю модель Vosk…")

            path = vosk_model.ensure_model(reporthook=hook)
            return True, f"Модель Vosk готова: {path.name}"

        if key == "whisper":
            from faster_whisper.utils import download_model

            name = _model_name(config)
            progress(None, f"Скачиваю модель whisper {name}: это долго и много мегабайт…")
            download_model(name, cache_dir=str(whisper_cache_dir()))
            progress(1.0, "Модель whisper скачана.")
            return True, f"Модель {name} в кэше {whisper_cache_dir().name}."

        if key == "piper":
            from jarvis.tts_engines.piper import PiperEngine

            voice, quality = piper_voice(config)
            progress(None, f"Скачиваю голос Piper {voice}/{quality} (~60 МБ)…")
            PiperEngine(voice, quality, 1.15)
            progress(1.0, "Голос Piper скачан.")
            return True, f"Голос {voice}/{quality} в кэше Hugging Face."

        if key == "silero":
            from jarvis.tts_engines.silero import SileroEngine

            progress(None, "Готовлю Silero: torch.hub скачает модель (~150 МБ)…")
            SileroEngine()
            progress(1.0, "Silero готов.")
            return True, "Модель Silero в torch-кэше."

        if key == "ollama":
            model = "qwen2.5:7b-instruct"
            url = "http://127.0.0.1:11434"
            if config is not None:
                model = str(config.get("llm_model") or model)
                url = str(config.get("ollama_url") or url)
            return _ollama_pull(url, model, progress)
    except Exception as error:
        log.exception("engines: установка %s не удалась", key)
        return False, f"Установка не удалась: {type(error).__name__}"
    return False, "Этот движок не скачивается: он системный или настраивается иначе."


