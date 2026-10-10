"""Собирает снимок проекта в один SNAPSHOT.md.

Задача: дать ЛЮБОЙ модели полное понимание проекта без доп. контекста,
не тратя зря окно. Поэтому снимок — не «комок всех файлов», а слои:

    0. PROJECT.md          курируемый источник правды (инварианты, правила,
                           история ошибок, контракт проверки)
    1. Карта проекта       дерево + строки + роль файла
    2. Смысл из кода       сигнатуры, константы, порядок pipeline, entry points
    3. Индекс кода         файл -> сколько строк и на что смотреть
    4. Код и данные        полный текст .py / .json / .bat / тестов

Режимы:
    (по умолчанию) lean   все слои + код с свернутыми длинными докстрингами;
                          markdown-доки не печатаются, их заменяет PROJECT.md
    --full                как раньше: полный текст доков и докстрингов
    --signatures          только слои 0-3, кода нет совсем (~85% экономии)
    --budget-kb N         режет по приоритету: код -> доки -> паки
    --include-docs        вернуть полный текст .md в lean
    --check               сравнить с имеющимся SNAPSHOT.md, не записывая

Отличия от старой версии:
    * fence считается по содержимому файла. Раньше файл, внутри которого
      есть ```, заворачивался в ```markdown, внешний fence закрывался
      раньше времени и половина дампа рендерилась как код.
    * вывод детерминированный: в шапке sha256 вместо timestamp. Раньше
      файл был «грязным» в git всегда, даже когда ничего не менялось.
    * guard на секреты: password/token/api_key с непустым значением
      редактируется в ***.
    * CLI через argparse вместо нуля аргументов.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "SNAPSHOT.md"

# -----------------------------------------------------------------
# Исключения
# -----------------------------------------------------------------

EXCLUDE_DIRS = {
    ".git", "__pycache__",
    ".venv", ".venv311", "venv", "env", "envs",
    "logs", "models", "dist", "build", ".pytest_cache",
    ".idea", ".vscode", "node_modules",
    ".mypy_cache", ".ruff_cache",
    "voices",
    "profiles",       # личные данные - не в снимок
    "sounds",
}

EXCLUDE_FILES = {
    "config.json",
    "system_caps.json",
    "user_profile.json",
    "dialog.json",
    "timers.json",
    "tasks.json",
    "SNAPSHOT.md",        # сам себя не печатаем
    ".gitignore",
    "config.json.lock",
    "user_profile.json.lock",
    "profile.json.lock",
    "PROJECT.md.orig",
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
    ".ps1", ".sh", ".env", ".gitignore", ".iss",
}

MAX_FILE_SIZE = 200 * 1024

# Доки, которые печатаются целиком. Остальные .md в lean-режиме
# заменяются оглавлением: они дублируют PROJECT.md.
DOCS_FULL = {"PROJECT.md"}

# Приоритет для --budget. Что режем первым.
PRIORITY_ORDER = ["pack", "doc", "data", "code"]

# Редакция секретов: ключ с непустым значением.
SECRET_RE = re.compile(
    r'(?i)("[^"\n]*(?:password|passwd|token|api[_-]?key|secret)[^"\n]*"\s*:\s*)"([^"\n]+)"'
)


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Прячет значения похожие на секреты. Возвращает (текст, что нашлось)."""
    hits: list[str] = []

    def _sub(m: re.Match) -> str:
        value = m.group(2)
        if not value or value in ("***", "null", "sha256:"):
            return m.group(0)
        hits.append(m.group(1)[:60])
        return f'{m.group(1)}"***"'

    return SECRET_RE.sub(_sub, text), hits


def fence_for(content: str) -> str:
    """Длина fence по содержимому: самая длинная серия backticks + 1.

    Иначе вложенные ``` рвут внешний блок и дамп читается как код.
    """
    longest = max((len(m) for m in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


# -----------------------------------------------------------------
# Сбор файлов
# -----------------------------------------------------------------

def should_skip_dir(path: Path) -> bool:
    name = path.name
    if name in EXCLUDE_DIRS:
        return True
    # .venvXXX / venvXXX / envXXX
    if name.startswith((".venv", "venv", "env")) and len(name) <= 12:
        return True
    return False


def should_skip_file(path: Path) -> bool:
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix.lower() in EXCLUDE_EXT:
        return True
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return True
    except OSError:
        return True
    return False


def collect_files(root: Path) -> list[Path]:
    """Все файлы для снимка, отсортированные по приоритету.

    Порядок: PROJECT.md -> код -> скрипты/тесты -> корневые .py -> данные
    -> доки. Чтобы --budget резал с менее важного конца.
    """
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if should_skip_file(path):
            continue
        found.append(path)

    def _rank(p: Path) -> tuple[int, str]:
        rel = p.relative_to(root).as_posix()
        if rel == "PROJECT.md":
            return (0, rel)
        if rel.startswith("jarvis/"):
            return (1, rel)
        if rel.startswith(("scripts/", "tests/")):
            return (2, rel)
        if p.suffix == ".py":
            return (3, rel)
        if p.suffix in (".json", ".bat", ".cmd", ".iss", ".yml"):
            return (4, rel)
        if p.suffix == ".md":
            return (6, rel)
        return (5, rel)

    return sorted(found, key=_rank)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="cp1251")
        except Exception:
            return ""
    except Exception:
        return ""


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def kind_of(path: Path) -> str:
    """Категория для приоритета: code / data / pack / doc."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "code"
    if suffix in (".json", ".bat", ".cmd", ".iss", ".yml", ".yaml"):
        return "pack" if path.parent.name == "packs" else "data"
    if suffix == ".md":
        return "doc"
    return "data"



# -----------------------------------------------------------------
# Слой 2: смысл из кода, через ast
# -----------------------------------------------------------------

def _sig(node) -> str:
    """Сигнатура функции через ast.unparse (Python 3.9+)."""
    try:
        args = ast.unparse(node.args)
    except Exception:
        return "(...)"
    args = re.sub(r"\s+", " ", args).strip()
    if len(args) > 110:
        args = args[:107] + "..."
    return f"({args})"


def _list_literal(node) -> str:
    """Распаковывает return [...] в элементы одной строкой.

    Так в снимок попадает фактический порядок pipeline и реестра,
    который иначе пришлось бы вычитывать глазами.
    """
    if not isinstance(node, ast.Return) or not isinstance(node.value, ast.List):
        return ""
    items = []
    for el in node.value.elts:
        try:
            items.append(ast.unparse(el))
        except Exception:
            continue
    if not items:
        return ""
    joined = ", ".join(items)
    return joined if len(joined) <= 220 else joined[:217] + "..."


def extract_meaning(path: Path) -> list[str]:
    """Сигнатуры, константы, порядок pipeline, точки входа.

    Самый дешевый способ передать «что умеет модуль»: ~5% размера файла.
    """
    src = read_text(path)
    if not src:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"  !! СИНТАКСИС СЛОМАН: {e.msg} (строка {e.lineno})"]

    out: list[str] = []

    doc = ast.get_docstring(tree)
    if doc:
        out.append(f"  # {doc.strip().splitlines()[0][:110]}")

    has_main = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    out.append(f"  {target.id} = ...")
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id.isupper():
                out.append(f"  {target.id}: ...")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and node.name != "__init__":
                continue
            kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            # Ищем return [...] по всему телу: body[0] почти всегда
            # докстринг, и на нём _list_literal молча ничего не находил.
            literal = ""
            for stmt in node.body:
                literal = _list_literal(stmt)
                if literal:
                    break
            if literal:
                out.append(f"  {kw} {node.name}{_sig(node)} -> [{literal}]")
            else:
                out.append(f"  {kw} {node.name}{_sig(node)}")
        elif isinstance(node, ast.ClassDef):
            bases = ""
            if node.bases:
                try:
                    bases = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
                except Exception:
                    bases = "(...)"
            out.append(f"  class {node.name}{bases}")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("_") and sub.name != "__init__":
                        continue
                    kw = "async def" if isinstance(sub, ast.AsyncFunctionDef) else "def"
                    out.append(f"    {kw} {sub.name}{_sig(sub)}")
                elif isinstance(sub, ast.AnnAssign):
                    target = sub.target
                    if isinstance(target, ast.Name) and target.id.isupper():
                        out.append(f"    {target.id}: ...")
        elif isinstance(node, ast.If):
            try:
                if ast.unparse(node.test) == '__name__ == "__main__"':
                    has_main = True
            except Exception:
                pass

    if has_main:
        out.append("  >>> ТОЧКА ВХОДА (__main__)")
    if "ft.run(" in src:
        out.append("  >>> GUI: ft.run(...) - Flet в главном потоке")
    return out


def collapse_docstrings(src: str, max_lines: int = 3) -> str:
    """Сворачивает докстринги длиннее max_lines в одну строку.

    Здесь живет экономия lean-режима: в проекте 74 КБ докстрингов,
    и они в основном дублируют PROJECT.md.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src

    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if not (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        if first.end_lineno - first.lineno + 1 <= max_lines:
            continue
        doc = first.value.value.strip()
        head = (doc.splitlines()[0] if doc else "").replace('"""', "'''")[:90]
        spans.append((first.lineno, first.end_lineno, head))

    if not spans:
        return src

    lines = src.splitlines()
    # С конца - иначе поедут номера строк
    for start, end, head in sorted(spans, reverse=True):
        indent = re.match(r"\s*", lines[start - 1]).group(0)
        lines[start - 1:end] = [f'{indent}"""{head} ... [{end - start} строк]"""']

    return "\n".join(lines) + ("\n" if src.endswith("\n") else "")



# -----------------------------------------------------------------
# Слои снимка
# -----------------------------------------------------------------

def build_tree(files: list[Path], root: Path) -> str:
    """Дерево проекта. У файлов — сколько строк."""
    tree: dict = {}
    for p in files:
        parts = p.relative_to(root).parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = p

    def render(node: dict, indent: str = "") -> list[str]:
        out: list[str] = []
        items = sorted(node.items(), key=lambda x: (x[1] is not None, x[0].lower()))
        for name, sub in items:
            if sub is None:
                out.append(f"{indent}├── {name}")
            elif isinstance(sub, Path):
                out.append(f"{indent}├── {name}  ({count_lines(sub)} стр)")
            else:
                out.append(f"{indent}├── {name}/")
                out.extend(render(sub, indent + "│   "))
        return out

    return "\n".join(render(tree))


def section_code(files: list[Path], root: Path, mode: str,
                 budget_kb: float | None,
                 secrets: list[str]) -> list[str]:
    """Слой 4: полный текст кода и данных."""
    out: list[str] = []
    used = 0.0
    limit = budget_kb * 1024 if budget_kb else None

    for p in files:
        rel = p.relative_to(root).as_posix()
        suffix = p.suffix.lower()
        kind = kind_of(p)

        if suffix not in TEXT_EXT and suffix != "":
            out.append(f"### `{rel}`\n")
            out.append(f"_Нетекстовый файл: {suffix or 'без расширения'}_\n")
            continue

        text = read_text(p)
        if not text:
            continue

        # PROJECT.md уже напечатан слоем 0 — второй раз не нужен
        if p.name == "PROJECT.md":
            continue

        # lean: докстринги сворачиваем. Полный текст .md печатаем только
        # в --full / --include-docs, иначе он дублирует PROJECT.md.
        if kind == "code":
            if mode in ("lean", "full-docs"):
                text = collapse_docstrings(text)
        elif kind == "doc" and p.name not in DOCS_FULL:
            if mode not in ("full", "full-docs"):
                continue

        text, hits = redact_secrets(text)
        secrets.extend(f"{rel}: {h}" for h in hits)

        size = len(text.encode("utf-8"))
        if limit is not None and used + size > limit and out:
            out.append(f"### `{rel}`\n")
            out.append(f"_ОБРЕЗАНО по бюджету {budget_kb:.0f} КБ. "
                       f"Полный файл — в репозитории._\n")
            break
        used += size

        fence = fence_for(text)
        lang = {
            ".py": "python", ".md": "markdown", ".json": "json",
            ".bat": "batch", ".cmd": "batch", ".iss": "ini",
            ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
            ".ps1": "powershell", ".sh": "bash",
        }.get(suffix, "")

        out.append(f"### `{rel}`")
        out.append("")
        out.append(fence + lang)
        out.append(text.rstrip())
        out.append(fence)
        out.append("")

    return out


def section_docs(files: list[Path], root: Path) -> list[str]:
    """Для .md, которых нет в слое 4: только оглавление."""
    out: list[str] = []
    for p in files:
        if p.suffix.lower() != ".md" or p.name in DOCS_FULL:
            continue
        rel = p.relative_to(root).as_posix()
        headings = [ln.strip() for ln in read_text(p).splitlines()
                    if ln.startswith("#")]
        out.append(f"#### `{rel}` — {len(headings)} заголовков, "
                   f"полный текст не включён (дублирует PROJECT.md)")
        out.append("")
        for h in headings[:40]:
            level = len(h) - len(h.lstrip("#"))
            out.append(f"{'  ' * max(0, level - 1)}- {h.lstrip('# ')}")
        out.append("")
    return out



def build_snapshot(mode: str, budget_kb: float | None) -> tuple[str, list[str]]:
    """Собирает весь текст снимка. Возвращает (текст, найденные секреты)."""
    files = collect_files(BASE)
    secrets: list[str] = []

    digest = hashlib.sha256()
    total_bytes = 0
    total_lines = 0
    by_kind: dict[str, list[Path]] = {}
    for p in files:
        digest.update(p.relative_to(BASE).as_posix().encode())
        digest.update(b"\0")
        try:
            digest.update(p.read_bytes())
            total_bytes += p.stat().st_size
        except OSError:
            pass
        total_lines += count_lines(p)
        by_kind.setdefault(kind_of(p), []).append(p)

    code_files = [p for p in files if p.suffix == ".py"]
    L: list[str] = []

    L.append("# SNAPSHOT проекта «Феникс»")
    L.append("")
    L.append(f"`sha256={digest.hexdigest()[:16]}` · режим `{mode}` · "
             f"файлов `{len(files)}` · строк `{total_lines}` · "
             f"источник `{total_bytes / 1024:.0f} КБ`")
    L.append("")
    L.append("> Генерируется `snapshot.py`. Вывод детерминированный: "
             "содержимое меняется только когда меняются файлы.")
    L.append(">")
    L.append("> **Начинай с раздела 0 — PROJECT.md.** Там инварианты, правила "
             "и история ошибок. Дальше карта, смысл из кода, потом сам код.")
    L.append("")
    L.append("---")
    L.append("")

    # --- Слой 0: источник правды ---
    L.append("## 0. PROJECT.md — что это, как устроено, чего нельзя делать")
    L.append("")
    project_md = BASE / "PROJECT.md"
    if project_md.exists():
        text = read_text(project_md)
        text, hits = redact_secrets(text)
        secrets.extend(f"PROJECT.md: {h}" for h in hits)
        fence = fence_for(text)
        L.append(fence)
        L.append(text.rstrip())
        L.append(fence)
    else:
        L.append("_PROJECT.md отсутствует. Это источник правды — "
                 "создайте его, иначе снимок теряет смысловой слой._")
    L.append("")
    L.append("---")
    L.append("")

    # --- Слой 1: карта ---
    L.append("## 1. Карта проекта")
    L.append("")
    L.append("```")
    L.append(BASE.name + "/")
    L.append(build_tree(files, BASE))
    L.append("```")
    L.append("")

    # --- Слой 2: смысл из кода ---
    if mode != "signatures":
        L.append("## 2. Смысл из кода (сигнатуры, константы, порядок)")
        L.append("")
        for p in code_files:
            meaning = extract_meaning(p)
            if not meaning:
                continue
            L.append(f"**`{p.relative_to(BASE).as_posix()}`**")
            L.append("")
            L.append("```")
            L.extend(meaning)
            L.append("```")
            L.append("")

    # --- Слой 3: индекс ---
    L.append("## 3. Индекс кода")
    L.append("")
    L.append("| Файл | Строк | Категория | О чём модуль |")
    L.append("|---|---:|---|---|")
    for p in code_files:
        rel = p.relative_to(BASE).as_posix()
        about = ""
        try:
            doc = ast.get_docstring(ast.parse(read_text(p)))
            about = (doc or "").strip().splitlines()[0] if doc else ""
        except Exception:
            about = ""
        about = about.replace("|", "/")[:70]
        L.append(f"| `{rel}` | {count_lines(p)} | {kind_of(p)} | {about} |")
    L.append("")

    # --- Слой 4: код ---
    L.append("---")
    L.append("")
    L.append("## 4. Код и данные")
    L.append("")
    if mode == "signatures":
        L.append("_Режим `--signatures`: код не печатается. "
                 "Запустите без флага, чтобы получить полный текст._")
        L.append("")
    else:
        L.extend(section_code(files, BASE, mode, budget_kb, secrets))

    extra = section_docs(files, BASE)
    if extra:
        L.append("## 5. Документация (только оглавления)")
        L.append("")
        L.extend(extra)

    stats = ", ".join(f"{k}: {len(v)}" for k, v in sorted(by_kind.items()))
    L.append("---")
    L.append("")
    L.append(f"_Итого по категориям — {stats}. Режим `{mode}`._")
    L.append("")

    return "\n".join(L), secrets



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Собирает SNAPSHOT.md для Феникса.")
    ap.add_argument("--full", action="store_true",
                    help="полный текст доков и докстрингов (как старая версия)")
    ap.add_argument("--signatures", action="store_true",
                    help="только PROJECT.md + карта + смысл + индекс, без кода")
    ap.add_argument("--include-docs", action="store_true",
                    help="в lean вернуть полный текст .md")
    ap.add_argument("--budget-kb", type=float, default=None,
                    help="ограничить размер, резать с менее важного")
    ap.add_argument("--check", action="store_true",
                    help="сравнить с имеющимся SNAPSHOT.md и не записывать")
    ap.add_argument("--out", default=None, help="путь вместо SNAPSHOT.md")
    return ap.parse_args(argv)


def drift_reason(content: str, path: Path) -> list[str]:
    """Что изменилось относительно файла на диске. Для --check.

    Раньше --check печатал голое «УСТАРЕЛ», и если снимок чувствителен
    к любому новому файлу в проеконе (а он чувствителен — sha256 по всем
    файлам), причина была невидима. Теперь видно, что именно поехало.
    """
    if not path.exists():
        return ["файла нет — нужно сгенерировать"]
    disk = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if disk == content:
        return []

    def _head(text: str, key: str) -> str:
        m = re.search(rf"{key}\s*`([^`]+)`", text)
        return m.group(1) if m else "?"

    reasons = [
        f"sha256: на диске {_head(disk, 'sha256')} -> сейчас {_head(content, 'sha256')}",
        f"файлов:  на диске {_head(disk, 'файлов')} -> сейчас {_head(content, 'файлов')}",
    ]
    return reasons


def main() -> int:
    args = parse_args()
    out_path = Path(args.out) if args.out else OUTPUT

    if args.signatures:
        mode = "signatures"
    elif args.full:
        mode = "full"
    else:
        mode = "lean"

    if args.include_docs and mode == "lean":
        mode = "full-docs"

    print(f"Снимок проекта: {BASE}")
    print(f"Режим: {mode}")

    content, secrets = build_snapshot(mode, args.budget_kb)

    if secrets:
        print(f"ВНИМАНИЕ: похоже на секреты, отредактировано ({len(secrets)}):")
        for s in secrets[:10]:
            print(f"  - {s}")

    if args.check:
        reasons = drift_reason(content, out_path)
        if not reasons:
            print("CHECK: актуален")
            return 0
        print("CHECK: УСТАРЕЛ — перегенерируйте")
        for r in reasons:
            print(f"  - {r}")
        return 1

    out_path.write_text(content, encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"Готово: {out_path}")
    print(f"Размер: {size_kb:.1f} КБ, строк: {content.count(chr(10)) + 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

