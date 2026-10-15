"""Import boundaries must work in a fresh interpreter, before any pytest warmup.

The two password.py files are different layers, never interchangeable.
These tests don't import the application during test collection.
"""

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_password_primitives_are_not_the_pipeline_stage():
    tree = ast.parse((ROOT / "jarvis/intents/password.py").read_text(encoding="utf-8"))
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assignments = {
        t.id
        for n in tree.body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    assert {
        "hash_password",
        "verify_password",
        "migrate_password_if_needed",
        "is_danger",
    } <= functions
    assert {"ACTION_HUMAN", "DANGER_ACTIONS"} <= assignments
    assert not any(
        isinstance(n, ast.ClassDef) and n.name == "PasswordStage" for n in tree.body
    ), (
        "Pipeline stage was saved over jarvis/intents/password.py; restore both modules with their directories"
    )
    assert not any(
        isinstance(n, ast.ImportFrom) and n.module == "jarvis.intents.password"
        for n in ast.walk(tree)
    ), "Password primitives must not import themselves"


def test_password_stage_imports_primitives_not_itself():
    tree = ast.parse(
        (ROOT / "jarvis/intents/stages/password.py").read_text(encoding="utf-8")
    )
    assert any(
        isinstance(n, ast.ClassDef) and n.name == "PasswordStage" for n in tree.body
    )
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(n.module == "jarvis.intents.stages.password" for n in imports)
    assert any(
        n.module == "jarvis.intents.password"
        and {"ACTION_HUMAN", "verify_password"} <= {v.name for v in n.names}
        for n in imports
    )


@pytest.mark.parametrize(
    "first",
    [
        "jarvis.intents.password",
        "jarvis.intents.stages.password",
        "jarvis.intents.handler",
        "jarvis.intents.execute",
    ],
)
def test_password_and_handler_import_in_fresh_process(first, tmp_path):
    code = """
import importlib
from pathlib import Path
import sys
root = Path(sys.argv[2]).resolve()
importlib.import_module(sys.argv[1])
core = importlib.import_module('jarvis.intents.password')
stage = importlib.import_module('jarvis.intents.stages.password')
handler = importlib.import_module('jarvis.intents.handler')
assert Path(core.__file__).resolve() == root / 'jarvis/intents/password.py'
assert Path(stage.__file__).resolve() == root / 'jarvis/intents/stages/password.py'
assert core is not stage
assert callable(core.migrate_password_if_needed)
assert core.ACTION_HUMAN['clear_tasks']
assert core.verify_password('test-only', core.hash_password('test-only'))
assert not core.verify_password('wrong', core.hash_password('test-only'))
assert stage.PasswordStage.name == 'password'
assert callable(handler.IntentHandler)
print('Password primitives, stage and handler: OK')
"""
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "APPDATA": str(tmp_path),
        "PROGRAMDATA": str(tmp_path),
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, first, str(ROOT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, f"{first}:\n{result.stdout}\n{result.stderr}"
    assert "handler: OK" in result.stdout
