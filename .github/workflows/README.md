# Workflows

## test.yml

Основной CI. Запускается при `push` и `pull_request` в `main` / `master`.

**Что делает:**
1. Windows-виртуалка, Python 3.11, кэш pip.
2. `pip install -r requirements-ci.txt`.
3. `python check_syntax.py`.
4. `python -m pytest tests/ -q`.
5. `python tests/test_intents.py` (без флагов).
6. `python tests/stress_intents.py` (100 ситуаций, без LLM/сети; UIA-ситуации
   в CI проверяют понятный отказ — см. `CI.md`).

**Env:**
- `PYTHONUTF8=1` — UTF-8 mode интерпретатора.
- `PYTHONIOENCODING=utf-8` — для stdout/stderr.

**Timeout:** 15 минут.

**Если упало** — см. `CI.md` в корне репозитория.

## release.yml

Автосборка релиза. Запускается при пуше тега `v*`, а также вручную
(Actions → **build-release** → Run workflow).

**Что делает:**
1. Windows-виртуалка, Python 3.11, кэш pip.
2. `pip install -r requirements-dev.txt Pillow` (зависимости проекта не нужны:
   `Феникс.exe` — лёгкий лаунчер на чистой stdlib).
3. `choco install innosetup --no-progress -y` — Inno Setup 6.
4. `python scripts/build_setup.py --version <версия из тега>` — `.exe` + установщик.
5. Артефакты запуска: `Феникс.exe`, `dist/Феникс_Setup.exe`.
6. На теге — `gh release create` с двумя файлами и авто-заметками.

**Env:** `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` (в проекте кириллица в именах файлов).
**Права:** `contents: write` — без него релиз не создать.
**Timeout:** 40 минут (PyInstaller + Inno Setup).

**Версия:** тег `v1.0.2` → `1.0.2` → `/DMyAppVersion=1.0.2` в `installer.iss`.

**Если упало** — см. `CI.md`, раздел «Авторелиз».

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