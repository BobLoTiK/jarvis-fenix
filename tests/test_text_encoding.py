"""Test sources/fixtures are UTF-8, independent of Windows ANSI code page."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent


def explicit_encoding(call):
    """Path.read_text(encoding, ...) / write_text(data, encoding, ...)."""
    for keyword in call.keywords:
        if keyword.arg == 'encoding':
            return not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
    index = 0 if call.func.attr == 'read_text' else 1
    if len(call.args) > index:
        value = call.args[index]
        return not (isinstance(value, ast.Constant) and value.value is None)
    return False


@pytest.mark.parametrize('expression,expected', [
    ('p.read_text()', False),
    ('p.read_text(None)', False),
    ('p.read_text(encoding=None)', False),
    ('p.read_text("utf-8")', True),
    ('p.read_text(encoding="utf-8")', True),
    ('p.write_text("text")', False),
    ('p.write_text("text", None)', False),
    ('p.write_text("text", encoding=None)', False),
    ('p.write_text("text", "utf-8")', True),
    ('p.write_text("text", encoding="utf-8")', True),
])
def test_encoding_guard_recognizes_positional_and_keyword_arguments(expression, expected):
    assert explicit_encoding(ast.parse(expression, mode='eval').body) is expected


def test_test_files_do_not_use_locale_dependent_path_text_io():
    failures = []
    for path in sorted(ROOT.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {'read_text', 'write_text'} and not explicit_encoding(node)):
                failures.append(f'{path.relative_to(ROOT)}:{node.lineno}: {node.func.attr} requires encoding')
    assert not failures, '\n'.join(failures)
