"""Exercise real temporary Git indexes/hooks; never commit or alter the user's repo."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check_staged_snapshot.py"
INSTALLER = ROOT / "scripts/install_git_hooks.py"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("Git is required for temporary-index tests")
    # Do not inherit an active outer git-commit index or personal Git config.
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    global_config = tmp_path / "git-global"
    global_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("PYTHONUTF8", "1")
    root = tmp_path / "project with space"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    for name in [
        "snapshot.py",
        ".gitignore",
        ".gitattributes",
        ".githooks/pre-commit",
        "scripts/check_staged_snapshot.py",
    ]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    (root / "example.py").write_text("value = 1\n", encoding="utf-8")
    snapshot(root)
    git(root, "add", ".")
    return root


def git(root, *args, data=None):
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout


def snapshot(root):
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(root / "snapshot.py")],
        cwd=root,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def check(root):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(CHECKER), "--repo", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def install(root):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(INSTALLER), "--repo", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_staged_snapshot_passes_without_writes(repo):
    before = git(repo, "ls-files", "--stage", "-z")
    index = (repo / ".git/index").read_bytes()
    snap = (repo / "SNAPSHOT.md").read_bytes()
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo, "ls-files", "--stage", "-z") == before
    assert (repo / "SNAPSHOT.md").read_bytes() == snap
    assert (repo / ".git/index").read_bytes() == index


def test_stale_staged_snapshot_fails(repo):
    (repo / "example.py").write_text("value = 2\n", encoding="utf-8")
    git(repo, "add", "example.py")
    before = git(repo, "ls-files", "--stage", "-z")
    assert check(repo).returncode == 1
    assert git(repo, "ls-files", "--stage", "-z") == before


def test_fresh_unstaged_snapshot_cannot_hide_stale_index(repo):
    (repo / "example.py").write_text("value = 3\n", encoding="utf-8")
    git(repo, "add", "example.py")
    snapshot(repo)  # Deliberately NOT staged: a naive worktree --check would pass.
    assert check(repo).returncode == 1


def test_unstaged_edits_do_not_block_consistent_prepared_commit(repo):
    (repo / "example.py").write_text("value = 99\n", encoding="utf-8")
    snapshot(repo)
    assert check(repo).returncode == 0
    assert "99" in (repo / "example.py").read_text(encoding="utf-8")


def test_missing_staged_snapshot_blocks(repo):
    git(repo, "rm", "--cached", "SNAPSHOT.md")
    assert check(repo).returncode == 2
    assert (repo / "SNAPSHOT.md").exists()


def test_tracked_log_requires_explicit_untracking(repo):
    log = repo / "pytest-log.txt"
    log.write_text("private local test output\n", encoding="utf-8")
    git(repo, "add", "--force", "pytest-log.txt")
    result = check(repo)
    assert result.returncode == 2
    assert "git rm --cached" in result.stderr
    assert log.exists() and b"pytest-log.txt" in git(repo, "ls-files", "-z")
    git(repo, "rm", "--cached", "pytest-log.txt")
    assert check(repo).returncode == 0
    assert log.exists()


def test_test_log_is_ignored_and_does_not_change_snapshot(repo):
    before = (repo / "SNAPSHOT.md").read_bytes()
    (repo / "pytest-log.txt").write_text("829 passed\n", encoding="utf-8")
    assert git(repo, "check-ignore", "pytest-log.txt").strip() == b"pytest-log.txt"
    snapshot(repo)
    assert (repo / "SNAPSHOT.md").read_bytes() == before
    assert check(repo).returncode == 0


@pytest.mark.parametrize("name", [".env", ".env.local", ".ENV", ".envrc", "nested/.env.production"])
def test_dotenv_does_not_enter_snapshot(repo, name):
    before = (repo / "SNAPSHOT.md").read_bytes()
    private = repo / name
    private.parent.mkdir(parents=True, exist_ok=True)
    content = "FAKE_LOCAL_SECRET=dotenv_regression_fixture\n"
    private.write_text(content, encoding="utf-8")
    snapshot(repo)
    assert private.read_text(encoding="utf-8") == content
    assert (repo / "SNAPSHOT.md").read_bytes() == before
    assert b"dotenv_regression_fixture" not in (repo / "SNAPSHOT.md").read_bytes()
    assert check(repo).returncode == 0


def test_staged_doc_change_is_checked(repo):
    (repo / "GUIDE.md").write_text("# Test guide\n", encoding="utf-8")
    git(repo, "add", "GUIDE.md")
    assert check(repo).returncode == 1
    snapshot(repo)
    git(repo, "add", "SNAPSHOT.md")
    assert check(repo).returncode == 0


def test_spaces_and_unicode_paths(repo):
    p = repo / "tests" / "имя с пробелом.py"
    p.parent.mkdir()
    p.write_text("answer = 42\n", encoding="utf-8")
    snapshot(repo)
    git(repo, "add", ".")
    assert check(repo).returncode == 0


def test_index_symlink_input_is_rejected_without_creating_symlink(repo):
    oid = (
        git(repo, "hash-object", "-w", "--stdin", data=b"../outside")
        .strip()
        .decode("ascii")
    )
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},link.py")
    result = check(repo)
    assert result.returncode == 2
    assert "not a regular file" in result.stderr


def test_unmerged_index_is_rejected(repo):
    oid = git(repo, "hash-object", "-w", "--stdin", data=b"value=1\n").strip()
    records = (
        b"0 "
        + b"0" * len(oid)
        + b"\texample.py\n"
        + b"100644 "
        + oid
        + b" 2\texample.py\n"
        + b"100644 "
        + oid
        + b" 3\texample.py\n"
    )
    git(repo, "update-index", "--index-info", data=records)
    assert check(repo).returncode == 2


def test_install_is_opt_in_idempotent_and_preserves_other_hooks(repo):
    other = repo / ".git/hooks/commit-msg"
    other.write_bytes(b"#!/bin/sh\nexit 0\n")
    config = (repo / ".git/config").read_bytes()
    before = git(repo, "ls-files", "--stage", "-z")
    assert install(repo).returncode == 0
    hook = repo / ".git/hooks/pre-commit"
    assert b"\r" not in hook.read_bytes()
    assert install(repo).returncode == 0
    assert other.read_bytes() == b"#!/bin/sh\nexit 0\n"
    assert (repo / ".git/config").read_bytes() == config
    assert git(repo, "ls-files", "--stage", "-z") == before


def test_existing_pre_commit_is_never_overwritten(repo):
    hook = repo / ".git/hooks/pre-commit"
    hook.write_bytes(b"custom hook\n")
    assert install(repo).returncode == 2
    assert hook.read_bytes() == b"custom hook\n"


def test_existing_hooks_path_is_never_changed(repo):
    git(repo, "config", "core.hooksPath", "custom-hooks")
    assert install(repo).returncode == 2
    assert git(repo, "config", "--get", "core.hooksPath").strip() == b"custom-hooks"
    assert not (repo / ".git/hooks/pre-commit").exists()


def test_installed_hook_runs_actual_checker(repo):
    assert install(repo).returncode == 0
    result = subprocess.run(
        ["git", "-C", str(repo), "hook", "run", "pre-commit"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (repo / "example.py").write_text("value = 4\n", encoding="utf-8")
    git(repo, "add", "example.py")
    result = subprocess.run(
        ["git", "-C", str(repo), "hook", "run", "pre-commit"],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    # No commit was made, even in this disposable test repository.
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0


def test_not_a_repository_fails_clearly(tmp_path):
    assert check(tmp_path).returncode == 2
    assert install(tmp_path).returncode == 2


def test_clinerules_numbering_and_ignore_files_are_consistent():
    import re

    text = (ROOT / ".clinerules").read_text(encoding="utf-8")
    numbers = [int(n) for n in re.findall(r"^(\d+)\.", text, flags=re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1))
    for name in (".gitignore", ".clineignore"):
        assert (
            "/pytest-log.txt" in (ROOT / name).read_text(encoding="utf-8").splitlines()
        )
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in ("graphify-out/", ".audio-regression/", "audio-regression/"):
        assert lines.count(pattern) == 1


def test_windows_checkout_line_endings_with_lf_hook(repo):
    # Emulate Git-for-Windows checkout conversion without claiming Windows execution.
    git(repo, "config", "core.autocrlf", "true")
    for path in repo.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.name != "SNAPSHOT.md":
            text = path.read_text(encoding="utf-8")
            data = (
                text
                if path == repo / ".githooks/pre-commit"
                else text.replace("\n", "\r\n")
            )
            path.write_bytes(data.encode("utf-8"))
    snapshot(repo)
    git(repo, "add", "--renormalize", ".")
    git(repo, "add", "SNAPSHOT.md")
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert b"\r" not in (repo / ".githooks/pre-commit").read_bytes()


def test_mixed_svg_lf_and_windows_crlf_checkout(repo):
    """New LF assets stay LF locally; checkout-index converts them to CRLF."""
    git(repo, "config", "core.autocrlf", "true")
    for path in repo.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.name != "SNAPSHOT.md":
            data = path.read_bytes().replace(b"\r\n", b"\n")
            if path != repo / ".githooks/pre-commit":
                data = data.replace(b"\n", b"\r\n")
            path.write_bytes(data)
    asset = repo / "jarvis/assets/brand/dialog-dark.svg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg">\n</svg>\n')
    snapshot(repo)
    git(repo, "add", "-A")
    before = git(repo, "ls-files", "--stage", "-z")
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert asset.read_bytes().endswith(b"</svg>\n")
    assert git(repo, "ls-files", "--stage", "-z") == before


def test_snapshot_text_and_size_are_eol_independent(repo):
    asset = repo / "picture.svg"
    asset.write_bytes(b'<svg>\n<!-- text -->\n</svg>\n')
    snapshot(repo)
    before = (repo / "SNAPSHOT.md").read_text(encoding="utf-8")
    for path in repo.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.name != "SNAPSHOT.md":
            data = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(data.replace(b"\n", b"\r\n"))
    snapshot(repo)
    assert (repo / "SNAPSHOT.md").read_text(encoding="utf-8") == before
    asset.write_bytes(b'<svg>\n<!-- actual change -->\n</svg>\n')
    snapshot(repo)
    assert (repo / "SNAPSHOT.md").read_text(encoding="utf-8") != before
