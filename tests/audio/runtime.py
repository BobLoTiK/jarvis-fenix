"""Real ASR + production _process; only a bounded, side-effect-free command harness.

No config/profile load, threads, microphone, audio playback or external actions.
The limited open/timer pipeline is explicit in coverage, not a full app simulator.
"""

import importlib.util
import os
import socket
import threading
import time
from collections import deque
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.audio.suite import Blocked


def preflight(root, *, asr="hybrid", no_vad=False, vosk_model=None, whisper_model=None):
    if os.name != "nt":
        raise Blocked(
            "Полный аудиопрогон предназначен для Windows; pytest не требует Windows/моделей"
        )
    required = ["vosk", "numpy", "flet"]
    if not no_vad:
        required.append("onnxruntime")
    if asr == "hybrid":
        required += ["faster_whisper", "ctranslate2"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        raise Blocked("Нет установленных runtime-зависимостей: " + ", ".join(missing))
    from jarvis import model, paths, vad

    candidates = (
        [Path(vosk_model)]
        if vosk_model
        else [
            paths.program_models_dir() / model.MODEL_NAME,
            Path(root) / "models" / model.MODEL_NAME,
        ]
    )
    vosk = next(
        (
            p
            for p in candidates
            if (p / "am/final.mdl").is_file() and (p / "conf/model.conf").is_file()
        ),
        None,
    )
    if vosk is None:
        raise Blocked(
            "Нет локальной модели Vosk. Укажи --vosk-model; загрузка не запускается"
        )
    if not str(vosk.resolve()).isascii():
        raise Blocked("Путь модели Vosk должен быть ASCII")
    if not no_vad and vad._find_model() is None:
        raise Blocked(
            "Нет локальной silero_vad.onnx; запусти обычный Феникс для установки или явно --no-vad"
        )
    whisper = None
    if asr == "hybrid":
        if whisper_model:
            candidates = [Path(whisper_model)]
        else:
            from jarvis.config import DEFAULT_CONFIG

            repo = DEFAULT_CONFIG["whisper_model"].replace("/", "--")
            cache = (
                paths.program_whisper_cache_dir() / ("models--" + repo) / "snapshots"
            )
            candidates = sorted(
                cache.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True
            )
        whisper = next(
            (
                p
                for p in candidates
                if all(
                    (p / f).is_file()
                    for f in ("model.bin", "config.json", "tokenizer.json")
                )
            ),
            None,
        )
        if whisper is None:
            raise Blocked(
                "Нет локальной CTranslate2-модели Whisper. Укажи --whisper-model или явно --asr vosk"
            )
    return {"vosk": vosk.resolve(), "whisper": whisper.resolve() if whisper else None}


class Sandbox:
    def __init__(self, listener, whisper=None, *, app_class=None):
        self.stack = ExitStack()
        try:
            self._setup(listener, whisper, app_class=app_class)
        except BaseException:
            self.stack.close()
            raise

    def _setup(self, listener, whisper=None, *, app_class=None):
        from jarvis.config import DEFAULT_CONFIG
        from jarvis.intents.fast.open import open_fast
        from jarvis.intents.fast.timers import timers_fast
        from jarvis.intents.handler import IntentHandler
        from jarvis.intents.stages.cancel import CancelStage
        from jarvis.intents.stages.clarification import ClarificationStage
        from jarvis.intents.stages.compound import CompoundStage
        from jarvis.intents.stages.fast import FastHandlersStage
        from jarvis.intents.stages.pending import PendingStage

        if app_class is None:
            from jarvis.main import Jarvis

            app_class = Jarvis

        self.events, self.replies = [], []
        self.config = deepcopy(DEFAULT_CONFIG)
        self.config.update(
            prosody_enabled=False,
            observer_enabled=False,
            nonverbal_enabled=False,
            mode="commands",
            use_llm=False,
            vad_auto_download=False,
        )
        self.stack.enter_context(patch("jarvis.memory.append", lambda msg: None))
        self.stack.enter_context(patch("jarvis.mood.apply_from_text", lambda cmd: None))
        self.stack.enter_context(patch("jarvis.intents.fast.open._do_open", self._open))
        self.stack.enter_context(patch("jarvis.timers.add", self._timer))
        self.stack.enter_context(
            patch(
                "jarvis.timers.remove_all", lambda: self._forbidden("remove_all") or 0
            )
        )
        self.stack.enter_context(
            patch("jarvis.timers.list_all", lambda: self._forbidden("list_all") or [])
        )
        h = IntentHandler.__new__(IntentHandler)
        h.config, h.brain, h.mode = self.config, None, "commands"
        h.apps = [
            SimpleNamespace(
                key="notepad", title="Блокнот", aliases=["блокнот", "notepad"]
            ),
            SimpleNamespace(key="steam", title="Стим", aliases=["стим", "steam"]),
        ]
        h._installed, h._steam_games = {}, []
        h._pending_question = h._pending_password = None
        h._reset_requested = False
        h._last_cmd = h._raw_cmd = h._last_reply = ""
        h.dialog, h._recent_phrases = deque(maxlen=100), deque(maxlen=10)
        h.custom = []
        h._pipeline = [
            CancelStage(),
            PendingStage(),
            CompoundStage(),
            ClarificationStage(),
            FastHandlersStage(),
        ]
        h._fast_handlers_cache = [
            ("open", lambda cmd: open_fast(h, cmd)),
            ("timers", lambda cmd: timers_fast(h, cmd)),
        ]
        a = app_class.__new__(app_class)
        a.config, a.handler, a.listener, a.whisper = self.config, h, listener, whisper
        a.gui = a.observer = None
        a.cmd_lock = threading.Lock()
        a.speaker = SimpleNamespace(stop=lambda: None, wait_end=lambda **kw: True)
        a._wake_words, a._wake_word_required = list(DEFAULT_CONFIG["wake_words"]), True
        a._awaiting_until, a._last_repeat_at = 0.0, float("-inf")
        a.say = self._say
        self.app, self.handler = a, h

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stack.close()

    def _say(self, reply):
        if reply.is_stream:
            raise Blocked("В ограниченном аудионаборе потоковый LLM-ответ не разрешён")
        self.replies.append(reply.text or "")
        return False

    def _open(self, handler, target):
        self.events.append({"action": "open", "target": target})
        return "Открываю приложение (тест)."

    def _timer(self, text, fire_at):
        seconds = round(fire_at - time.time())
        self.events.append({"action": "timer", "seconds": seconds, "text": text})
        return {"id": 1, "text": text, "fire_at": fire_at}

    def _forbidden(self, action):
        self.events.append({"action": "blocked", "name": action})

    def process(self, text, pcm):
        self.app._process(text, pcm)

    def snapshot(self, event_start, reply_start, timing_before):
        pending = self.handler._pending_question
        return {
            "actions": self.events[event_start:],
            "pending": pending.get("slot") if pending else None,
            "replies": self.replies[reply_start:],
            "handled": getattr(self.handler, "_last_timings", None)
            is not timing_before,
        }


def check_expected(actual, expect, endpoints):
    errors = []
    if expect.get("speech", True) and endpoints < 1:
        errors.append("Vosk не отдал ни одной фразы через настоящий endpoint")
    if not expect.get("speech", True) and endpoints:
        errors.append("На тишине/шуме получен речевой endpoint")
    if actual["actions"] != expect["actions"]:
        errors.append("Действия не совпали с ожиданиями")
    if actual["pending"] != expect["pending"]:
        errors.append("Неверное состояние уточнения")
    if "handled" in expect and actual["handled"] != expect["handled"]:
        errors.append("Неверная маршрутизация wake/окна диалога")
    wanted = expect.get("reply_contains", "").lower()
    if wanted and not any(wanted in r.lower() for r in actual["replies"]):
        errors.append("Нет ожидаемого вопроса/ответа")
    return errors


def deny_network(*args, **kwargs):
    raise Blocked("Аудиорегрессия запрещает сетевые соединения")


class Engine:
    def __init__(self, models, *, asr="hybrid", no_vad=False, device="cpu"):
        self.stack = ExitStack()
        try:
            self._setup(models, asr=asr, no_vad=no_vad, device=device)
        except BaseException:
            self.stack.close()
            raise

    def _setup(self, models, *, asr="hybrid", no_vad=False, device="cpu"):
        from jarvis import stt, vad
        from jarvis.config import DEFAULT_CONFIG

        # No opt-out download switch: a measurement must use installed models.
        self.stack.enter_context(patch.object(socket.socket, "connect", deny_network))
        self.stack.enter_context(
            patch.object(socket.socket, "connect_ex", deny_network)
        )
        self.stack.enter_context(
            patch.object(socket, "create_connection", deny_network)
        )
        self.config = deepcopy(DEFAULT_CONFIG)
        self.config.update(vad_auto_download=False, vad_enabled=not no_vad)

        class StrictVAD(vad.VAD):
            fault = False

            def _max_prob(self, samples):
                try:
                    return super()._max_prob(samples)
                except Exception:
                    self.fault = True
                    raise

        class StrictWhisper(stt.WhisperTranscriber):
            fault = False
            calls = 0

            def transcribe(self, *args, **kwargs):
                self.calls += 1
                try:
                    return super().transcribe(*args, **kwargs)
                except Exception:
                    self.fault = True
                    raise

        self.stack.enter_context(patch.object(stt, "VAD", StrictVAD))
        self.stack.enter_context(patch.object(vad, "VAD", StrictVAD))
        try:
            self.listener = stt.Listener(
                models["vosk"], config=self.config, file_mode=True
            )
            self.whisper = None
            if asr == "hybrid":
                self.whisper = StrictWhisper(
                    str(models["whisper"]),
                    device=device,
                    config=self.config,
                    local_files_only=True,
                )
            self.no_vad = no_vad
            self._require_vad()
        except BaseException:
            self.stack.close()
            raise

    def _require_vad(self):
        v = self.listener.vad
        if not self.no_vad and (
            v is None
            or not v.is_available()
            or getattr(v, "fault", False)
            or getattr(v, "_auto_off", False)
        ):
            raise Blocked(
                "VAD недоступен/отключился/перешёл на fallback: полного измерения нет"
            )
        if self.listener.file_vad_errors:
            raise Blocked(
                "Ошибка callback VAD; fallback не считается успешной проверкой"
            )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stack.close()

    def new_case(self):
        # Noise adaptation must not leak between independent scenarios.
        if not self.no_vad:
            self.listener.reload_vad()
            self._require_vad()
        return Sandbox(self.listener, self.whisper)

    def replay(self, pcm, sandbox, *, include_transcripts=False):
        self.listener.reset_file_input()
        n_events, n_replies = len(sandbox.events), len(sandbox.replies)
        before = getattr(sandbox.handler, "_last_timings", None)
        started = time.perf_counter()
        whisper_before = self.whisper.calls if self.whisper else 0
        endpoints = []
        size = self.listener._block_size * 2
        for offset in range(0, len(pcm), size):
            block = pcm[offset : offset + size]
            # Silero works in 512-sample chunks, pad only the final block.
            if len(block) < size:
                block += b"\0" * (size - len(block))
            phrases = self.listener.feed_pcm(block)
            self._require_vad()
            for text, audio in phrases:
                endpoint = {
                    "audio_ms": round((offset + size) / 32, 2),
                    "quality": self.listener.last_quality.reason,
                }
                if include_transcripts:
                    endpoint["transcript"] = text
                endpoints.append(endpoint)
                sandbox.process(text, audio)
                if self.whisper is not None and self.whisper.fault:
                    raise Blocked(
                        "Whisper упал: fallback Vosk не считается hybrid pass"
                    )
            self._require_vad()
        actual = sandbox.snapshot(n_events, n_replies, before)
        return {
            **actual,
            "endpoints": endpoints,
            "whisper_calls": (self.whisper.calls - whisper_before)
            if self.whisper
            else 0,
            "wall_ms": round((time.perf_counter() - started) * 1000, 2),
            "audio_ms": round(len(pcm) / 32, 2),
        }
