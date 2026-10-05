# Workflows

## test.yml

Основной CI. Запускается при `push` и `pull_request` в `main` / `master`.

**Что делает:**
1. Windows-виртуалка, Python 3.11, кэш pip.
2. `pip install -r requirements-ci.txt`.
3. `python check_syntax.py`.
4. `python -m pytest tests/ -q`.
5. `python test_intents.py` (без флагов).

**Env:**
- `PYTHONUTF8=1` — UTF-8 mode интерпретатора.
- `PYTHONIOENCODING=utf-8` — для stdout/stderr.

**Timeout:** 15 минут.

**Если упало** — см. `CI.md` в корне репозитория.

## Как добавить новый workflow

Создай файл `.github/workflows/<name>.yml`:

```yaml
name: my-workflow
on: [push]
jobs:
  my-job:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: python my_script.py
```