"""Same-named package files have different roles; test real imports in fresh Python."""
import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("first", [
    "import jarvis",
    "from jarvis.intents import IntentHandler",
    "import jarvis.weather",
])
def test_fresh_package_imports(first, tmp_path):
    script = first + "\n" + """
import jarvis
from jarvis.intents import IntentHandler
from jarvis.intents.password import ACTION_HUMAN, hash_password, verify_password
from jarvis.intents.stages.password import PasswordStage
from jarvis.intents.stages import build_pipeline
import jarvis.weather
assert isinstance(jarvis.__version__, str) and jarvis.__version__
assert 'shutdown_pc' in ACTION_HUMAN
assert verify_password('synthetic-layout-test', hash_password('synthetic-layout-test'))
assert not verify_password('wrong', hash_password('synthetic-layout-test'))
assert callable(build_pipeline)
print('COLD_IMPORT_OK')
"""
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYSTRAY_BACKEND="dummy")
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA"):
        folder = tmp_path / key
        folder.mkdir()
        env[key] = str(folder)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COLD_IMPORT_OK" in result.stdout


def test_root_and_intents_init_keep_their_own_exports():
    root = ast.parse((ROOT / "jarvis/__init__.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets
    ) for n in root.body), "jarvis/__init__.py must define __version__; do not copy another __init__.py over it"
    package = ast.parse((ROOT / "jarvis/intents/__init__.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.ImportFrom) and n.module == "jarvis.intents.handler"
               and any(a.name == "IntentHandler" for a in n.names) for n in package.body)
    assert not any(isinstance(n, ast.ImportFrom) and (n.module or "").startswith("jarvis.intents.stages")
                   for n in package.body), "Stage registry belongs in intents/stages/__init__.py"


def test_password_primitives_are_not_replaced_by_password_stage():
    tree = ast.parse((ROOT / "jarvis/intents/password.py").read_text(encoding="utf-8"))
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"hash_password", "verify_password", "is_danger"} <= functions
    assert not any(isinstance(n, ast.ImportFrom) and n.module == "jarvis.intents.password"
                   for n in ast.walk(tree)), "Primitive module must not import itself; stages/password.py is a different file"
