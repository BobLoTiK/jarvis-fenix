"""«Выход» из трея обязан завершать процесс даже при зависшем Flet.

Окно закрывалось, но ft.run мог не вернуться: процесс оставался жить без
окна, микрофон продолжал слушать, а в консоли светилось «Феникс продолжает
слушать». Теперь при выходе поднимается сторож, который принудительно
завершает процесс, если штатный путь не уложился в отведённое время.
"""

import time
from types import SimpleNamespace

from jarvis import main as main_mod


def test_watchdog_waits_for_exit_request(monkeypatch):
    calls = []
    monkeypatch.setattr(main_mod.os, "_exit", lambda code: calls.append(code))
    gui = SimpleNamespace(_quitting=False)

    main_mod._arm_exit_watchdog(gui, grace=0.05)
    time.sleep(0.3)

    assert calls == [], "без «Выход» сторож не должен завершать процесс"


def test_watchdog_terminates_after_hung_exit(monkeypatch):
    calls = []
    monkeypatch.setattr(main_mod.os, "_exit", lambda code: calls.append(code))
    gui = SimpleNamespace(_quitting=False)

    main_mod._arm_exit_watchdog(gui, grace=0.05)
    gui._quitting = True
    time.sleep(0.6)

    assert calls == [0]
