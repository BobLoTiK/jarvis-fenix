"""Тесты config_manager: параллельная запись не рвёт файл."""
import json
import threading
import time
from pathlib import Path

from jarvis import config_manager


def test_parallel_writes(tmp_path):
    """20 потоков пишут разные ключи — все должны сохраниться."""
    target = tmp_path / "test.json"
    config_manager.save({}, path=target)

    def writer(i):
        config_manager.update(f"key_{i}", i, path=target)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(target.read_text(encoding="utf-8"))
    present = [k for k in data if k.startswith("key_")]
    assert len(present) == 20, f"Потерялись ключи: {present}"


def test_atomic_write_valid_json(tmp_path):
    """Если файл есть — он всегда валидный JSON."""
    target = tmp_path / "test.json"
    for i in range(50):
        config_manager.update("counter", i, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert "counter" in data


def test_load_nonexistent(tmp_path):
    """Несуществующий файл — возвращает {}."""
    assert config_manager.load(path=tmp_path / "nope.json") == {}


def test_load_broken(tmp_path):
    """Битый файл — возвращает {}, не падает."""
    bad = tmp_path / "bad.json"
    bad.write_text("{это не json", encoding="utf-8")
    assert config_manager.load(path=bad) == {}