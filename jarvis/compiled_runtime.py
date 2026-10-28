"""Standalone app startup and explicit offline probes; no venv/pip bootstrap."""
import argparse
import asyncio
import importlib
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

log = logging.getLogger("jarvis.compiled")

PROBE_MODULES = (
    "numpy", "vosk", "sounddevice", "piper", "onnxruntime", "faster_whisper",
    "ctranslate2", "torch", "torchaudio", "flet", "flet_desktop", "pyttsx3",
    "pyttsx3.drivers.sapi5", "comtypes", "pycaw.pycaw", "uiautomation",
    "winrt.windows.media.control", "pymorphy3", "pymorphy3_dicts_ru", "num2words",
    "certifi", "jarvis.main",
)
RESOURCE_FILES = (
    "jarvis/icon.ico", "jarvis/assets/brand/phoenix-dark.png",
    "jarvis/assets/brand/phoenix-light.png", "assets/nonverbal/hmm.wav",
    "packs/games.json", "config.example.json", "LICENSE",
    "runtime/flet/flet.exe", "runtime/flet/flutter_windows.dll", "runtime/flet/data/icudtl.dat",
)


def configure_environment(root):
    """Force the packaged Flet client; no ~/.flet cache or host Python needed."""
    root = Path(root).resolve()
    client = root / "runtime" / "flet"
    if not (client / "flet.exe").is_file():
        raise FileNotFoundError("В сборке отсутствует runtime/flet/flet.exe")
    os.environ["FLET_VIEW_PATH"] = str(client)
    os.environ["FLET_DESKTOP_FLAVOR"] = "full"
    os.environ["FLET_APP_USER_MODEL_ID"] = "Phoenix.Nuitka"
    from jarvis.https_trust import configure_https_trust
    configure_https_trust()
    # Flet checks cwd/build/windows before FLET_VIEW_PATH. Use the curated app root.
    os.chdir(root)



def configure_com_cache():
    """Generate machine-specific COM wrappers in user data, not Program Files."""
    from importlib.machinery import ModuleSpec
    from types import ModuleType
    from jarvis import paths
    cache = paths.user_dir() / "comtypes-cache"
    cache.mkdir(parents=True, exist_ok=True)
    import comtypes
    try:
        gen = importlib.import_module("comtypes.gen")
    except ModuleNotFoundError as exc:
        if exc.name != "comtypes.gen":
            raise
        # comtypes normally creates this dynamic package by writing next to itself.
        gen = ModuleType("comtypes.gen")
        gen.__package__ = "comtypes.gen"
        gen.__spec__ = ModuleSpec("comtypes.gen", loader=None, is_package=True)
        sys.modules["comtypes.gen"] = gen
        comtypes.gen = gen
    gen.__path__ = [str(cache)]
    client = importlib.import_module("comtypes.client")
    client.gen_dir = str(cache)
    return cache


def prepare_native_imports():
    # Native import order matters on Windows; no COM initialization before CT2.
    from jarvis.main import _preload_whisper_backend
    _preload_whisper_backend()
    configure_com_cache()


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="phoenix-report-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(report, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def self_test(root, *, compiled):
    """Offline structural/native probe. Does not claim microphone/voice/LLM success."""
    root = Path(root).resolve()
    report = {"schema": 1, "kind": "standalone-native-probe", "ok": False,
              "compiled": bool(compiled), "external_python_required": False,
              "root": str(root), "checks": {},
              "not_tested": ["microphone", "physical_audio", "voice_models", "Ollama", "GPU_inference"]}
    checks = report["checks"]
    checks["compiled_entry"] = bool(compiled)
    checks["resources"] = all((root / p).is_file() for p in RESOURCE_FILES)
    checks["flet_assets"] = (root / "runtime/flet/data/flutter_assets").is_dir()
    checks["no_external_interpreter"] = not any(
        (root / name).exists() for name in ("python.exe", "pythonw.exe", ".venv311", "launcher.py"))
    for name in PROBE_MODULES:
        try:
            module = importlib.import_module(name)
            filename = getattr(module, "__file__", None)
            if not filename or not Path(filename).resolve().is_relative_to(root):
                raise RuntimeError("Module loaded outside the standalone distribution")
            checks[name] = True
        except Exception as exc:
            checks[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        import torch
        # Silero needs TorchScript. Default standalone JIT disabling is not acceptable.
        traced = torch.jit.trace(lambda x: x + 1, torch.zeros(1))
        buffer = io.BytesIO()
        torch.jit.save(traced, buffer)
        buffer.seek(0)
        loaded = torch.jit.load(buffer, map_location="cpu")
        checks["torchscript_cpu"] = float(loaded(torch.zeros(1))[0]) == 1.0
    except Exception as exc:
        checks["torchscript_cpu"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        import pymorphy3
        checks["russian_dictionary"] = bool(pymorphy3.MorphAnalyzer().parse("проверка"))
    except Exception as exc:
        checks["russian_dictionary"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    report["ok"] = all(value is True for value in checks.values())
    return report


def gui_smoke(root, destination, *, compiled):
    """Exercise packaged Flet without a Vosk download or opening the microphone."""
    report = {"schema": 1, "kind": "flet-desktop-smoke", "compiled": bool(compiled),
              "ok": False, "session_opened": False, "window_close_awaited": False,
              "not_tested": ["assistant_workflow", "microphone", "physical_audio", "Ollama"]}
    try:
        import flet as ft
        async def page_main(page):
            page.title = "Феникс — проверка автономной сборки"
            page.add(ft.Text("Автономный Flet-клиент запущен без внешнего Python."))
            page.update()
            report["session_opened"] = True
            write_report(destination, report)
            await asyncio.sleep(2)
            page.window.prevent_close = False
            await page.window.close()
            report["window_close_awaited"] = True
        ft.run(page_main, assets_dir=str(Path(root) / "jarvis/assets"), view=ft.AppView.FLET_APP)
        report["ok"] = bool(compiled and report["session_opened"] and report["window_close_awaited"])
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    write_report(destination, report)
    return 0 if report["ok"] else 1


def prepare_silero(session):
    """Explicit consent is required before Torch Hub runs a new repository's code."""
    if not session.ask(
        "Silero загружает модель и выполняет код репозитория snakers4/silero-models. "
        "Разрешить загрузку и доверять этому репозиторию?",
        "Подготовка Silero", "Разрешить", "Отмена",
    ):
        session.notice = "Подготовка Silero отменена. Можно использовать Piper или SAPI."
        return False
    from jarvis import paths
    os.environ.setdefault("TORCH_HOME", str(paths.program_dir() / "torch"))
    import torch
    session.stage("Подготовка Silero", "Загружаем модель. Внешний Python не требуется.", show=True)
    torch.hub.load("snakers4/silero-models", "silero_tts", language="ru",
                   speaker="v5_5_ru", trust_repo=True)
    return True


def prepare_application(root, log_file, *, silero_only=False):
    from launcher_ui import PreparationWindow
    completed = {"ok": False}
    def job(session):
        if silero_only:
            completed["ok"] = prepare_silero(session)
            return
        from jarvis import model, paths
        target = paths.program_models_dir() / model.MODEL_NAME
        if not model.model_is_ready(target):
            if not session.ask(
                "Для распознавания речи нужна модель Vosk (~45 МБ). Скачать её? "
                "Python и зависимости уже находятся внутри приложения.",
                "Первый запуск", "Скачать модель", "Отмена",
            ):
                session.notice = "Загрузка модели отменена."
                return
            session.stage("Модель распознавания", "Загрузка Vosk", show=True)
            model.ensure_model(Path(root) / "models", reporthook=session.download_progress)
        # Preserve native import order before COM/WinRT capabilities checks.
        from jarvis.main import _preload_whisper_backend
        _preload_whisper_backend()
        from scripts import check_caps
        session.stage("Проверка возможностей", "Проверяем компоненты этого компьютера.")
        if check_caps.main(["--if-missing"]) != 0:
            raise RuntimeError("Не удалось проверить возможности Windows")
        completed["ok"] = True
    PreparationWindow(Path(root), Path(log_file)).run(job)
    return completed["ok"]


def run(argv=None, *, root, compiled):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--self-test", metavar="REPORT_JSON")
    modes.add_argument("--gui-smoke", metavar="REPORT_JSON")
    modes.add_argument("--prepare-silero", action="store_true")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("Автономное приложение предназначено для Windows x64.", file=sys.stderr)
        return 1
    from jarvis import paths
    log_file = paths.logs_dir() / "compiled-startup.log"
    logging.basicConfig(filename=log_file, encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        configure_environment(root)
        if not args.gui_smoke:
            prepare_native_imports()
        if args.self_test:
            report = self_test(root, compiled=compiled)
            write_report(args.self_test, report)
            return 0 if report["ok"] else 1
        if args.gui_smoke:
            return gui_smoke(root, args.gui_smoke, compiled=compiled)
        if not prepare_application(root, log_file, silero_only=args.prepare_silero):
            return 2
        if args.prepare_silero:
            return 0
        from jarvis.main import main
        main()
        return 0
    except Exception as exc:
        log.exception("Не удалось запустить автономный Феникс")
        destination = args.self_test or args.gui_smoke
        if destination:
            write_report(destination, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        else:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0, f"Не удалось запустить Феникс.\nЖурнал: {log_file}\n\n{exc}", "Феникс", 0x10)
            except Exception:
                pass
        return 1
