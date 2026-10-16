"""Execute the real watchdog method without importing Windows/audio backends."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


def watchdog():
    path=Path(__file__).resolve().parents[1]/"jarvis/main.py"
    tree=ast.parse(path.read_text(encoding="utf-8"))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="Jarvis")
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="mic_watchdog")
    env={"log":logging.getLogger("watchdog-test")}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),"exec"),env)
    return env["mic_watchdog"]


@pytest.mark.parametrize("peak",[0,10,49,50,500])
def test_watchdog_never_speaks_or_steals_navigation(peak,caplog):
    core=NS(config={"mic_check_sec":20},stop_event=NS(wait=Mock(return_value=False)),
        listener=NS(peak=peak,device_name="Test mic"),say=Mock(),gui=NS(_queue=Mock()))
    with caplog.at_level(logging.INFO):watchdog()(core)
    core.say.assert_not_called();core.gui._queue.put.assert_not_called()
    core.stop_event.wait.assert_called_once_with(20)
    if peak<50:assert "Микрофон молчит" in caplog.text


def test_watchdog_disabled_or_shutdown_does_not_read_listener():
    for disabled,stopped in [(True,False),(False,True)]:
        core=NS(config={"mic_watchdog_enabled":not disabled},
            stop_event=NS(wait=Mock(return_value=stopped)),say=Mock(),gui=Mock())
        watchdog()(core)
        core.say.assert_not_called();core.gui._queue.put.assert_not_called()
