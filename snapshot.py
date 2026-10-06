"""Собирает снимок проекта в один SNAPSHOT.md.

Исключения: логи, кэш, модели, личные данные.
Запуск: python snapshot.py
Результат: SNAPSHOT.md в корне проекта.
"""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "SNAPSHOT.md"

EXCLUDE_DIRS = {
    ".git", "__pycache__",
    ".venv", ".venv311", "venv", "env", "envs",
    "logs", "models", "dist", "build", ".pytest_cache",
    ".idea", ".vscode", "node_modules",
    ".mypy_cache", ".ruff_cache",
    "voices",
    "profiles",   # №1: личные данные — НЕ в снимок
}

EXCLUDE_FILES = {
    "config.json",
    "user_profile.json",
    "dialog.json",
    "timers.json",
    "tasks.json",
    "SNAPSHOT.md",
    ".gitignore",
    "config.json.lock",
    "user_profile.json.lock",
    "ft.Control",
    "None",
    "python",
    "str",
}

EXCLUDE_EXT = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin",
    ".onnx", ".wav", ".mp3", ".zip", ".7z", ".rar",
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".bmp",
    ".tmp", ".lock", ".log",
}

TEXT_EXT = {
    ".py", ".md", ".txt", ".json", ".bat", ".cmd", ".cfg", ".ini",
    ".yaml", ".yml", ".toml", ".html", ".css", ".js", ".ts",
    ".ps1", ".sh", ".env", ".gitignore",
}

MAX_FILE_SIZE = 200 * 1024


def should_skip_dir(path: Path) -> bool:
    name = path.name
    # Явные исключения
    if name in EXCLUDE_DIRS:
        return True
    # Любая папка вида .venvXXX, venvXXX, envXXX
    if name.startswith((".venv", "venv", "env")) and len(name) <= 12:
        return True
    return False


def should_skip_file(path: Path) -> bool:
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix.lower() in EXCLUDE_EXT:
        return True
    if path.stat().st_size > MAX_FILE_SIZE:
        return True
    return False


def collect_tree(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if should_skip_file(path):
            continue
        result.append(path)
    return result


def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="cp1251")
        except Exception:
            return f"[бинарный или нечитаемый файл: {path.suffix}]"
    except Exception as e:
        return f"[ошибка чтения: {e}]"


def build_tree_text(paths: list[Path], root: Path) -> str:
    tree = {}
    for p in paths:
        rel = p.relative_to(root)
        parts = rel.parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None

    def render(node, indent=""):
        lines = []
        items = sorted(node.items(), key=lambda x: (x[1] is None, x[0].lower()))
        for name, sub in items:
            if sub is None:
                lines.append(f"{indent}├── {name}")
            else:
                lines.append(f"{indent}├── {name}/")
                lines.extend(render(sub, indent + "│   "))
        return lines

    return "\n".join(render(tree))


def main() -> int:
    print(f"Сбор снимка проекта: {BASE}")
    files = collect_tree(BASE)
    print(f"Найдено файлов: {len(files)}")

    lines = []
    lines.append("# SNAPSHOT проекта «Феникс»")
    lines.append("")
    lines.append(f"_Автоматически сгенерировано `snapshot.py`. Обновляется при `git push`._")
    lines.append(f"_Файлов в снимке: {len(files)}_")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📁 Структура проекта")
    lines.append("")
    lines.append("```")
    lines.append(BASE.name + "/")
    lines.append(build_tree_text(files, BASE))
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📄 Содержимое файлов")
    lines.append("")

    for i, path in enumerate(files, 1):
        rel = path.relative_to(BASE)
        suffix = path.suffix.lower()

        lines.append(f"### `{rel}`")
        lines.append("")

        if suffix not in TEXT_EXT and suffix != "":
            lines.append(f"_Бинарный или нетекстовый файл: {path.suffix or 'без расширения'}_")
            lines.append("")
            continue

        content = read_file(path)
        lang = {
            ".py": "python",
            ".md": "markdown",
            ".json": "json",
            ".bat": "batch",
            ".cmd": "batch",
            ".html": "html",
            ".css": "css",
            ".js": "javascript",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".ps1": "powershell",
            ".sh": "bash",
            ".ini": "ini",
            ".cfg": "ini",
        }.get(suffix, "")

        lines.append(f"```{lang}")
        lines.append(content.rstrip())
        lines.append("```")
        lines.append("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"Готово: {OUTPUT}")
    print(f"Размер: {size_kb:.1f} КБ, строк: {len(lines)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())