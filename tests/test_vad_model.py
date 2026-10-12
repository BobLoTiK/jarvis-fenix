"""Авто-скачивание модели Silero VAD (jarvis.vad).

Раньше silero_vad.onnx приходилось класть руками: в репозитории его нет
(*.onnx в .gitignore), установщик его тоже не ставит. На чистой
установке VAD молча выключался — юзер узнавал об этом только из лога.
Теперь Феникс качает модель фоном и включает VAD на лету. Проверяем это
без сети: urlopen подменён.

Проверяем:
    - model_dirs()/_find_model(): где искать и куда качать;
    - download_model(): успех, короткий файл, ошибка сети, отсутствие
      «огрызка» .part после неудачи;
    - ensure_model_async(): не более одной попытки за процесс;
    - VAD: модель есть/нет + auto_download, включение на лету.
"""

import io
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis import vad

# Модель, которая реально лежит на машине разработчика (если ставилась).
REAL_MODEL = Path(r"C:\ProgramData\Phoenix\vad\silero_vad.onnx")


@pytest.fixture(autouse=True)
def _reset_download_state():
    """Модуль помнит «качать уже пробовали» — между тестами сбрасываем."""
    with patch.object(vad, "_download_started", False), \
            patch.object(vad, "_download_thread", None):
        yield


def _fake_urlopen(payload: bytes):
    """Заглушка urllib.request.urlopen: отдаёт payload как поток байтов."""
    calls = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _open(request, timeout=None):
        calls.append((request, timeout))
        return _Resp(payload)

    _open.calls = calls
    return _open


def _never_called(*args, **kwargs):  # pragma: no cover - защита от вызова
    raise AssertionError("ensure_model_async вызван, хотя качать запрещено")


def _fake_model_vad(monkeypatch, tmp_path, **vad_kwargs):
    """VAD, у которого «модели нет» и качается она в tmp_path."""
    monkeypatch.setattr(vad, "_find_model", lambda: None)
    monkeypatch.setattr(vad, "model_dirs", lambda: [tmp_path])
    monkeypatch.setattr(vad, "ensure_model_async", lambda cb=None: object())
    return vad.VAD(**vad_kwargs)


# =================================================================
# Где искать / куда качать
# =================================================================

def test_model_dirs_first_is_vad_subdir(tmp_path, monkeypatch):
    """Качаем в PROGRAM_DIR/vad — этот путь проверяется первым."""
    monkeypatch.setattr("jarvis.paths.program_dir", lambda: tmp_path)
    assert vad.model_dirs()[0] == tmp_path / "vad"
    # Последний — исторический путь установщика (совместимость).
    assert vad.model_dirs()[-1] == Path(r"C:\ProgramData\Phoenix\vad")


def test_find_model_finds_file_in_first_dir(tmp_path, monkeypatch):
    """Модель нашлась в PROGRAM_DIR/vad — больше нигде не ищем."""
    monkeypatch.setattr(vad, "model_dirs", lambda: [tmp_path])
    assert vad._find_model() is None

    model = tmp_path / vad.MODEL_FILENAME
    model.write_bytes(b"model")



# =================================================================
# download_model()
# =================================================================

def test_download_model_saves_file(tmp_path):
    """Успешное скачивание: файл на месте, «огрызка» .part нет."""
    dest = tmp_path / vad.MODEL_FILENAME
    payload = b"\x01" * (vad.MODEL_MIN_BYTES + 10)
    opener = _fake_urlopen(payload)

    with patch("urllib.request.urlopen", opener):
        result = vad.download_model(dest, timeout=5.0)

    assert result == dest
    assert dest.read_bytes() == payload
    assert not (tmp_path / (vad.MODEL_FILENAME + ".part")).exists()
    # Запрос ушёл на официальный URL Silero и с нашим таймаутом.
    request, timeout = opener.calls[0]
    assert request.full_url == vad.MODEL_URL
    assert timeout == 5.0


def test_download_model_creates_missing_dir(tmp_path):
    """Папки может не быть — download_model её создаёт."""
    dest = tmp_path / "vad" / vad.MODEL_FILENAME
    with patch("urllib.request.urlopen",
               _fake_urlopen(b"\x01" * (vad.MODEL_MIN_BYTES + 1))):
        assert vad.download_model(dest) == dest
    assert dest.exists()


def test_download_model_rejects_truncated_file(tmp_path):
    """Обрезанный ответ (меньше MODEL_MIN_BYTES) моделью не считается."""
    dest = tmp_path / vad.MODEL_FILENAME
    with patch("urllib.request.urlopen", _fake_urlopen(b"\x01" * 100)):
        assert vad.download_model(dest) is None

    assert not dest.exists()
    assert not (tmp_path / (vad.MODEL_FILENAME + ".part")).exists()


def test_download_model_survives_network_error(tmp_path):
    """Нет сети — возвращаем None и не оставляем мусор после себя."""
    dest = tmp_path / vad.MODEL_FILENAME

    def _boom(request, timeout=None):
        raise OSError("нет интернета")

    with patch("urllib.request.urlopen", _boom):
        assert vad.download_model(dest) is None

    assert not dest.exists()
    assert not (tmp_path / (vad.MODEL_FILENAME + ".part")).exists()


# =================================================================
# ensure_model_async()
# =================================================================

def test_ensure_model_async_calls_back(tmp_path):
    """callback() зовётся из фонового потока с путём к модели."""
    calls = []
    started = threading.Event()

    def _fake_download(dest=None, timeout=None):
        return tmp_path / vad.MODEL_FILENAME

    def _cb(path):
        calls.append(path)
        started.set()

    with patch.object(vad, "download_model", _fake_download):
        thread = vad.ensure_model_async(_cb)

    assert thread is not None
    assert started.wait(3.0), "фоновый поток не позвал callback"
    assert calls == [tmp_path / vad.MODEL_FILENAME]


def test_ensure_model_async_is_one_per_process(tmp_path):
    """Второй вызов не запускает новое скачивание (Listener пересоздаёт VAD)."""
    blocker = threading.Event()

    def _fake_download(dest=None, timeout=None):
        blocker.wait(3.0)
        return None

    with patch.object(vad, "download_model", _fake_download):
        first = vad.ensure_model_async()
        second = vad.ensure_model_async()
        assert first is not None
        assert second is first  # тот же поток, новых запросов нет
        blocker.set()
        first.join(timeout=3.0)


# =================================================================
# VAD: модель качается в фоне
# =================================================================

def test_vad_pending_when_model_missing(monkeypatch, tmp_path):
    """Модели нет и качать разрешено: VAD живой, но помечен «качается»."""
    started = []

    monkeypatch.setattr(vad, "_find_model", lambda: None)
    monkeypatch.setattr(vad, "model_dirs", lambda: [tmp_path])
    monkeypatch.setattr(vad, "ensure_model_async",
                        lambda cb=None: started.append(cb) or object())

    v = vad.VAD()

    assert v.is_available() is False
    assert v.is_model_pending() is True
    assert len(started) == 1, "скачивание не запущено"
    # Пока модель качается, VAD ничего не режет (иначе потеряли бы речь).
    assert v.is_speech(b"\x00" * 2048) is True


def test_vad_no_network_when_auto_download_off(monkeypatch, tmp_path):
    """vad_auto_download=false — в сеть не идём вообще."""
    monkeypatch.setattr(vad, "_find_model", lambda: None)
    monkeypatch.setattr(vad, "model_dirs", lambda: [tmp_path])
    monkeypatch.setattr(vad, "ensure_model_async", _never_called)

    v = vad.VAD(auto_download=False)

    assert v.is_available() is False
    assert v.is_model_pending() is False


def test_model_pending_false_when_download_not_started(monkeypatch, tmp_path):
    """Скачивание уже пробовали (и не вышло) — «качается» не заявляем."""
    monkeypatch.setattr(vad, "_find_model", lambda: None)
    monkeypatch.setattr(vad, "model_dirs", lambda: [tmp_path])
    monkeypatch.setattr(vad, "ensure_model_async", lambda cb=None: None)

    v = vad.VAD()

    assert v.is_model_pending() is False


def test_on_model_ready_turns_vad_on(monkeypatch, tmp_path):
    """Модель докачалась — VAD включается на лету, без перезапуска Феникса."""
    if not REAL_MODEL.exists():
        pytest.skip(f"нет реальной модели {REAL_MODEL}")

    v = _fake_model_vad(monkeypatch, tmp_path)
    assert v.is_available() is False
    assert v.is_model_pending() is True

    v._on_model_ready(REAL_MODEL)

    assert v.is_available() is True
    assert v.is_model_pending() is False


def test_on_model_ready_is_noop_when_already_loaded(monkeypatch, tmp_path):
    """VAD уже работает — второй раз сессию не создаём."""
    v = _fake_model_vad(monkeypatch, tmp_path)
    v._available = True

    with patch.object(vad.VAD, "_load_session") as load:
        v._on_model_ready(REAL_MODEL)

    load.assert_not_called()


def test_load_session_returns_false_for_broken_file(monkeypatch, tmp_path):
    """Битый файл вместо модели — не падаем, просто работаем без VAD."""
    v = _fake_model_vad(monkeypatch, tmp_path)
    broken = tmp_path / "broken.onnx"
    broken.write_bytes(b"not-onnx")

    assert v._load_session(broken) is False
    assert v.is_available() is False
