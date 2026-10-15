"""Audio fixture contents must never become Windows environment-variable values."""

import ast
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
AUDIO_TESTS = ["tests/test_recognition_quality.py", "tests/test_nonverbal.py", "tests/test_audio_regression.py"]


def test_audio_case_ids_are_short_without_dumping_pcm():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *AUDIO_TESTS],
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    nodes = [line for line in result.stdout.splitlines() if "::test_" in line]
    assert nodes, "No audio tests collected"
    assert max(map(len, nodes)) < 512, "PCM data leaked into a pytest node ID"
    pcm_cases = [
        n for n in nodes if "::test_invalid_silent_or_clipped_audio_rejected[" in n
    ]
    assert len(pcm_cases) == 6
    assert all("\\x" not in n for n in nodes)


def test_audio_source_reads_have_explicit_utf8():
    for name in AUDIO_TESTS:
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "read_text":
                    assert any(
                        kw.arg == "encoding"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value == "utf-8"
                        for kw in node.keywords
                    ), f"{name}:{node.lineno} relies on the OS default encoding"
