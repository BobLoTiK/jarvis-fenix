"""Плагины: манифест, запуск в отдельном процессе, свои настройки.

Первый вертикальный срез, а не SDK: ядро Феникса остаётся владельцем микрофона,
команд и ответов, а плагин объявляет пару «фразы → действие» и получает вызов
через обычный текстовый pipeline (`intents/stages/plugins.py`).

Правила первого шага:

- манифест `plugin.json` рядом с кодом плагина; только read-only возможности
  (`command`, `status`, `settings`) — запись файлов/сеть/процессы запрещены
  самим объявлением, ядро такие манифесты отклоняет;
- код плагина запускается **в отдельном процессе** с таймаутом и убийством по
  таймауту; упавший плагин не роняет ядро, а его хвост stdout/stderr обрезается
  в лог;
- явное согласие: `plugins_enabled=false` по умолчанию, и даже при включённом
  флаге запускаются только имена из `plugins_allowed`;
- настройки плагина лежат в его собственном каталоге, отдельно от `config.json`;
- денег, магазина и лицензирования здесь нет и быть не должно.
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.paths import user_dir

log = logging.getLogger("jarvis.plugins")

MANIFEST_NAME = "plugin.json"
READ_ONLY_CAPABILITIES = frozenset({"command", "status", "settings"})
MAX_COMMANDS = 20
MAX_PHRASES = 10
MAX_OUTPUT = 16 * 1024
MAX_TIMEOUT = 30.0
_NAME_RE = re.compile(r"^[a-z0-9_-]{2,40}$")


class PluginError(Exception):
    """Манифест или плагин нарушает договор — честный отказ, не «пропустим»."""


@dataclass(frozen=True)
class PluginCommand:
    phrases: tuple[str, ...]
    action: str
    description: str = ""


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    entry: str
    commands: tuple[PluginCommand, ...]
    capabilities: tuple[str, ...]
    timeout_sec: float = 5.0
    description: str = ""
    path: Path | None = None

    @property
    def root(self) -> Path:
        return self.path if self.path is not None else Path(".")

    def phrase_map(self) -> dict[str, PluginCommand]:
        mapping = {}
        for command in self.commands:
            for phrase in command.phrases:
                mapping[" ".join(phrase.lower().split())] = command
        return mapping

    @classmethod
    def from_json(cls, path) -> "PluginManifest":
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PluginError(f"не читается: {exc}") from None
        except json.JSONDecodeError as exc:
            raise PluginError(f"битый JSON: {exc.msg}") from None
        if not isinstance(raw, dict):
            raise PluginError("манифест должен быть JSON-объектом")
        name = str(raw.get("name") or "").strip().lower()
        if not _NAME_RE.match(name):
            raise PluginError("name: 2–40 символов [a-z0-9_-]")
        version = str(raw.get("version") or "").strip()
        if not version:
            raise PluginError("version обязателен")
        entry = str(raw.get("entry") or "").strip()
        if not entry or Path(entry).is_absolute() or ".." in Path(entry).parts:
            raise PluginError("entry: файл внутри каталога плагина")
        root = path.parent.resolve()
        entry_path = (root / entry).resolve()
        if root not in entry_path.parents and entry_path != root:
            raise PluginError("entry выходит за каталог плагина")
        if not entry_path.is_file():
            raise PluginError(f"entry не найден: {entry}")

        capabilities = raw.get("capabilities", [])
        if not isinstance(capabilities, list) or not capabilities:
            raise PluginError("capabilities обязателен")
        normalized = tuple(str(item).strip().lower() for item in capabilities)
        unknown = [item for item in normalized if item not in READ_ONLY_CAPABILITIES]
        if unknown:
            raise PluginError("возможность вне первого шага: " + ", ".join(unknown))

        raw_commands = raw.get("commands", [])
        if not isinstance(raw_commands, list) or not raw_commands:
            raise PluginError("commands обязателен")
        if len(raw_commands) > MAX_COMMANDS:
            raise PluginError(f"слишком много команд (> {MAX_COMMANDS})")
        commands = []
        for item in raw_commands:
            if not isinstance(item, dict):
                raise PluginError("команда должна быть объектом")
            phrases = item.get("phrases")
            action = str(item.get("action") or "").strip()
            if not isinstance(phrases, list) or not phrases or len(phrases) > MAX_PHRASES:
                raise PluginError(f"phrases: 1–{MAX_PHRASES} строк")
            clean = [str(p).strip() for p in phrases if isinstance(p, str) and str(p).strip()]
            if not clean:
                raise PluginError("phrases пустые")
            if not action:
                raise PluginError("action обязателен")
            commands.append(PluginCommand(tuple(clean), action,
                                          str(item.get("description") or "")))
        try:
            timeout = float(raw.get("timeout_sec", 5.0))
        except (TypeError, ValueError):
            timeout = 5.0
        timeout = max(0.5, min(MAX_TIMEOUT, timeout))
        return cls(name=name, version=version, entry=entry,
                   commands=tuple(commands), capabilities=normalized,
                   timeout_sec=timeout,
                   description=str(raw.get("description") or ""), path=root)


@dataclass(frozen=True)
class PluginResult:
    ok: bool
    text: str = ""
    error: str = ""
    elapsed: float = 0.0


class PluginRunner:
    """Запуск плагина отдельным процессом. `popen` можно подменить в тестах."""

    def __init__(self, *, popen=None, python=None):
        self._popen = popen or self._default_popen
        self.python = python or sys.executable

    def _default_popen(self, argv, cwd):
        env = dict(os.environ)
        # Даже с `-I` (он игнорирует PYTHON*) оставляем подсказку для
        # интерпретатора без изоляции и для диагностики; основной механизм
        # UTF-8 — аргумент `-X utf8` в argv.
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        kwargs = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                  "stderr": subprocess.PIPE, "cwd": str(cwd), "env": env}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        return subprocess.Popen(argv, **kwargs)

    def run(self, manifest: PluginManifest, payload: dict) -> PluginResult:
        started = time.monotonic()
        entry = manifest.root / manifest.entry
        # `-I` отключает PYTHON* переменные окружения (это `-E`), поэтому
        # PYTHONIOENCODING здесь не действует: UTF-8 для stdin/stdout задаётся
        # явным `-X utf8`. Без него на русской Windows ответ плагина приходит
        # в cp1251 и ломается при чтении (поймано живым прогоном hello).
        argv = [self.python, "-I", "-X", "utf8", str(entry)]
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            process = self._popen(argv, manifest.root)
        except OSError as exc:
            return PluginResult(False, error=f"не запустился: {exc}")
        try:
            out, err = process.communicate(input=body, timeout=manifest.timeout_sec)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.communicate(timeout=5)
            except Exception:
                log.debug("плагин %s не убился", manifest.name, exc_info=True)
            return PluginResult(False, elapsed=time.monotonic() - started,
                                error=f"таймаут {manifest.timeout_sec:.1f} с")
        except Exception as exc:
            return PluginResult(False, elapsed=time.monotonic() - started,
                                error=f"сбой запуска: {exc}")
        elapsed = time.monotonic() - started
        code = getattr(process, "returncode", 0)
        stdout = (out or b"").decode("utf-8", "replace")[:MAX_OUTPUT].strip()
        stderr = (err or b"").decode("utf-8", "replace")[:MAX_OUTPUT].strip()
        if code not in (0, None):
            log.warning("плагин %s упал (код %s): %s", manifest.name, code,
                        stderr[-300:] or "без stderr")
            return PluginResult(False, elapsed=elapsed,
                                error=f"плагин упал (код {code})")
        text = stdout
        if stdout.startswith("{"):
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                if data.get("error"):
                    return PluginResult(False, elapsed=elapsed,
                                        error=str(data["error"])[:200])
                text = str(data.get("text") or "")
        return PluginResult(True, text=text, elapsed=elapsed)


class PluginSettings:
    """Настройки плагина: только его собственный JSON, атомарная запись."""

    def __init__(self, manifest: PluginManifest, base_dir=None):
        self.manifest = manifest
        root = Path(base_dir) if base_dir is not None else manifest.root
        self.path = root / f"{manifest.name}.settings.json"

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def set(self, key: str, value) -> None:
        if not isinstance(key, str) or not key or len(key) > 64:
            raise ValueError("ключ настройки: 1–64 символа")
        data = self.load()
        data[key] = value
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


@dataclass
class PluginState:
    manifest: PluginManifest
    started: bool = False
    started_at: float = 0.0
    settings: PluginSettings | None = None


class PluginHost:
    """Каталог плагинов, согласие человека и один запуск на команду."""

    def __init__(self, directory=None, *, runner=None, allowed=None,
                 config=None, settings_dir=None):
        self.directory = Path(directory) if directory is not None else user_dir() / "plugins"
        self.runner = runner or PluginRunner()
        self.config = config
        self.allowed = set()
        self._settings_dir = Path(settings_dir) if settings_dir is not None else None
        self.states: dict[str, PluginState] = {}
        self.errors: list[tuple[str, str]] = []
        if allowed is None and config is not None:
            raw = config.get("plugins_allowed", [])
            allowed = raw if isinstance(raw, list) else []
        for name in allowed or []:
            if isinstance(name, str):
                self.allowed.add(name.strip().lower())

    # --- жизнь -----------------------------------------------------

    def discover(self) -> list[PluginManifest]:
        """Читает манифесты. Ошибки — в `errors`, а не падение ядра."""
        self.states.clear()
        self.errors = []
        if not self.directory.is_dir():
            return []
        loaded = []
        for manifest_path in sorted(self.directory.glob(f"*/{MANIFEST_NAME}")):
            try:
                manifest = PluginManifest.from_json(manifest_path)
            except PluginError as exc:
                self.errors.append((manifest_path.parent.name, str(exc)))
                log.warning("плагин %s отклонён: %s", manifest_path.parent.name, exc)
                continue
            if manifest.name in self.states:
                self.errors.append((manifest.name, "имя уже занято"))
                continue
            settings = PluginSettings(
                manifest, self._settings_dir if self._settings_dir is not None
                else manifest.root)
            self.states[manifest.name] = PluginState(manifest, settings=settings)
            loaded.append(manifest)
        return loaded

    def start(self, name: str) -> tuple[bool, str]:
        state = self.states.get(str(name).strip().lower())
        if state is None:
            return False, f"Плагин {name} не найден."
        if state.manifest.name not in self.allowed:
            return False, ("Плагин не разрешён: добавьте его имя в plugins_allowed "
                           "в настройках.")
        state.started = True
        state.started_at = time.monotonic()
        log.info("Плагин %s запущен", state.manifest.name)
        return True, f"Плагин {state.manifest.name} запущен."

    def stop(self, name: str) -> tuple[bool, str]:
        state = self.states.get(str(name).strip().lower())
        if state is None or not state.started:
            return False, f"Плагин {name} не запущен."
        state.started = False
        log.info("Плагин %s остановлен", state.manifest.name)
        return True, f"Плагин {state.manifest.name} остановлен."

    def running(self) -> list[PluginManifest]:
        return [state.manifest for state in self.states.values() if state.started]

    # --- вызов -----------------------------------------------------

    def try_handle(self, cmd: str) -> str | None:
        """Ищет команду среди запущенных плагинов; None — не наше."""
        text = " ".join((cmd or "").lower().split())
        if not text:
            return None
        for state in self.states.values():
            if not state.started:
                continue
            command = state.manifest.phrase_map().get(text)
            if command is None:
                continue
            payload = {"command": command.action, "phrase": text, "text": cmd,
                       "settings": state.settings.load() if state.settings else {}}
            result = self.runner.run(state.manifest, payload)
            if not result.ok:
                log.warning("плагин %s: %s", state.manifest.name, result.error)
                return f"Плагин {state.manifest.name} не ответил: {result.error}"
            return result.text or f"Плагин {state.manifest.name} выполнил {command.action}."
        return None
