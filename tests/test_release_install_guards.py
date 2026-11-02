"""Стражи установщика: пины, файлы данных и понятные падения Silero.

Эти проверки появились после отчёта с чистой машины по v2.1.2: там одновременно
выстрелили незапертая зависимость (filelock), отсутствующие assets у
faster-whisper и невнятная ошибка «lost sys.stdin» вместо инструкции.
"""
import pathlib
import re
import threading

import pytest

from jarvis import cache_maintenance, compiled_runtime
from jarvis.tts_engines import silero

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_filelock_keeps_upper_bound():
    """Без верхней границы установка «на свежую машину» ломает FileLock."""
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("filelock")]
    assert lines, "filelock должен оставаться в requirements.txt"
    for line in lines:
        assert re.search(r"filelock>=3\.13,<4", line), f"нет верхней границы: {line}"


def test_build_tools_are_pinned_for_reproducible_exe():
    """Версии сборщика зафиксированы: от них зависит содержимое exe.

    Незапиненный pyinstaller-hooks-contrib дал разницу 12 003 916 Б против
    11 016 477 Б на одном коммите, и именно CI-файл пометил Defender.
    """
    text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "pyinstaller==" in text, "pyinstaller не запинен"
    assert "pyinstaller-hooks-contrib==" in text, "pyinstaller-hooks-contrib не запинен"


def test_nuitka_package_data_covers_faster_whisper():
    """--include-module не копирует assets: silero_vad_v6.onnx без этого теряется."""
    text = (ROOT / "scripts/build_nuitka_app.py").read_text(encoding="utf-8")
    block = re.search(r"DATA_PACKAGES\s*=\s*\((.*?)\)\n", text, re.S)
    assert block, "DATA_PACKAGES не найден"
    assert "faster_whisper" in block.group(1)


def test_self_test_verifies_filelock_and_vad_assets():
    """self-test обязан проверять то, что читается с диска, а не только import."""
    assert "filelock" in compiled_runtime.PROBE_MODULES
    source = (ROOT / "jarvis/compiled_runtime.py").read_text(encoding="utf-8")
    assert "faster_whisper_assets" in source
    assert "faster_whisper/assets/silero_vad_v6.onnx" in source


def test_console_prompt_failure_detection():
    assert silero._is_console_prompt_failure(RuntimeError("lost sys.stdin"))
    assert silero._is_console_prompt_failure(EOFError("EOF when reading a line"))
    assert not silero._is_console_prompt_failure(RuntimeError("сеть недоступна"))


class _FakeHub:
    def __init__(self, directory):
        self._directory = directory

    def get_dir(self):
        return str(self._directory)

    def load(self, **_kwargs):
        raise RuntimeError("lost sys.stdin")


class _FakeTorch:
    def __init__(self, directory):
        self.hub = _FakeHub(directory)


def test_silero_explains_console_prompt_instead_of_raw_stdin_error(tmp_path):
    """Пользователь должен увидеть инструкцию, а не «lost sys.stdin»."""
    (tmp_path / "trusted_list").write_text("snakers4_silero-models\r\n", encoding="utf-8")
    engine = silero.SileroEngine.__new__(silero.SileroEngine)
    engine._model = None
    engine._lock = threading.RLock()
    engine._device = "cpu"
    engine._torch = _FakeTorch(tmp_path)
    with pytest.raises(RuntimeError, match="prepare-silero"):
        engine._load_model()


def test_silero_keeps_real_failures_visible(tmp_path):
    """Настоящая ошибка сети не подменяется подсказкой про консоль."""
    class _BrokenHub(_FakeHub):
        def load(self, **_kwargs):
            raise RuntimeError("connection reset by peer")

    engine = silero.SileroEngine.__new__(silero.SileroEngine)
    engine._model = None
    engine._lock = threading.RLock()
    engine._device = "cpu"
    engine._torch = _FakeTorch(tmp_path)
    engine._torch.hub = _BrokenHub(tmp_path)
    (tmp_path / "trusted_list").write_text("snakers4_silero-models\r\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="connection reset"):
        engine._load_model()


def test_purge_stale_bytecode_once_per_version(tmp_path):
    root = tmp_path / "app"
    (root / "pkg/__pycache__").mkdir(parents=True)
    (root / "pkg/__pycache__/stale.pyc").write_bytes(b"old")
    (root / ".venv311/lib/__pycache__").mkdir(parents=True)
    marker = tmp_path / "bytecode-version.txt"

    assert cache_maintenance.purge_stale_bytecode("2.2.0", root=root, marker=marker) == 1
    assert not (root / "pkg/__pycache__").exists()
    # Чужой кэш (venv) не наш: не трогаем.
    assert (root / ".venv311/lib/__pycache__").exists()
    assert marker.read_text(encoding="utf-8") == "2.2.0"
    # Вторая проверка при той же версии ничего не делает.
    assert cache_maintenance.purge_stale_bytecode("2.2.0", root=root, marker=marker) == 0


def test_purge_survives_missing_directory(tmp_path):
    assert cache_maintenance.purge_stale_bytecode(
        "2.2.0", root=tmp_path / "нет-такого", marker=tmp_path / "m.txt") == 0
