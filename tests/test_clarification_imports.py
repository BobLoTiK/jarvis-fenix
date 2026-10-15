"""The slot engine and pipeline stage share a basename, not their contents.

No application imports at collection: diagnose accidental file replacement and
check actual package initialization in separate, cold Python interpreters.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "jarvis/intents/clarification.py"
STAGE = ROOT / "jarvis/intents/stages/clarification.py"


def test_slot_engine_defines_api_and_does_not_import_itself_or_pipeline():
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert {"begin", "resume", "pending_alive"} <= functions, (
        "Restore jarvis/intents/clarification.py: it must contain the slot engine, "
        "not the similarly named stages/clarification.py"
    )
    assert not any(
        isinstance(node, ast.ClassDef) and node.name == "ClarificationStage"
        for node in tree.body
    ), "Pipeline stage was placed in the slot-engine file"
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    assert not any(
        name in {"jarvis.intents.clarification", "jarvis.intents.handler"}
        or name == "jarvis.intents.stages"
        or name.startswith("jarvis.intents.stages.")
        for name in imports
    ), "Slot engine must not import itself or the pipeline that imports it"


def test_clarification_stage_delegates_to_engine_not_itself():
    tree = ast.parse(STAGE.read_text(encoding="utf-8"))
    assert any(
        isinstance(node, ast.ClassDef) and node.name == "ClarificationStage"
        for node in tree.body
    )
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert any(
        node.module == "jarvis.intents.clarification"
        and "begin" in {alias.name for alias in node.names}
        for node in imports
    )
    assert not any(
        node.module == "jarvis.intents.stages.clarification" for node in imports
    )
    assert CORE.read_bytes() != STAGE.read_bytes()


@pytest.mark.parametrize(
    "first",
    [
        "jarvis.intents.clarification",
        "jarvis.intents.stages.clarification",
        "jarvis.intents.handler",
    ],
    ids=["engine-first", "stage-first", "handler-first"],
)
def test_clarification_imports_in_fresh_process(first, tmp_path):
    code = """
import importlib
from pathlib import Path
import sys
root = Path(sys.argv[2]).resolve()
importlib.import_module(sys.argv[1])
core = importlib.import_module('jarvis.intents.clarification')
stage = importlib.import_module('jarvis.intents.stages.clarification')
handler = importlib.import_module('jarvis.intents.handler')
assert Path(core.__file__).resolve() == root / 'jarvis/intents/clarification.py'
assert Path(stage.__file__).resolve() == root / 'jarvis/intents/stages/clarification.py'
assert core is not stage
assert all(callable(getattr(core, name)) for name in ('begin', 'resume', 'pending_alive'))
assert stage.begin is core.begin
assert stage.ClarificationStage.name == 'clarification'
assert callable(handler.IntentHandler)
print('Clarification engine, stage and handler: OK')
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
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"{first}:\n{result.stdout}\n{result.stderr}"
    assert "Clarification engine, stage and handler: OK" in result.stdout
