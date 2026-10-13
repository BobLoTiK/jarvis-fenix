# CI — что это и как с ним жить

## 🎯 Что такое CI

CI = Continuous Integration = автоматическая проверка кода при каждом push.

GitHub Actions запускает виртуалку с Windows, ставит Python, зависимости,
прогоняет тесты. Через ~40 секунд ты видишь: ✅ или ❌.

**Зачем:** ловит регрессии, пока ты спишь. Не нужно помнить про тесты —
GitHub запускает их сам.

## 📁 Где лежит

- `.github/workflows/test.yml` — тесты на `push` и `pull_request`.
- `.github/workflows/release.yml` — автосборка и релиз по тегу `v*`.

## 🔍 Что делает

1. Checkout — скачивает код.
2. Setup Python 3.11 + кэш pip.
3. `pip install -r requirements-ci.txt` — облегчённые зависимости.
4. `python check_syntax.py` — синтаксис.
5. `python -m pytest tests/ -q` — юнит-тесты.
6. `python tests/test_intents.py` — интент-тесты без флагов.
7. `python tests/stress_intents.py` — стресс-тест: 100 ситуаций.

`PYTHONUTF8=1` — глобально на весь job, страховка от cp1252.

## 🚀 Как смотреть результат

1. Открой репозиторий на GitHub.
2. Вкладка **Actions**.
3. Последний запуск — ✅ или ❌.
4. Кликни → увидишь шаги и логи.

## 🔧 Если упало

**Шаг `Check syntax`** — синтаксис сломан. Открой лог, найди файл и строку.

**Шаг `pytest`** — юнит-тест упал. Лог покажет какой.

**Шаг `Intent tests`** — интент-тест упал. Логи в артефактах Actions или
локально `logs/test_intents.log` (в конце вывода — блок «ПРОВАЛЫ»).

**Шаг `Stress test`** — стресс-тест: 100 ситуаций. Лог `logs/stress_intents.log`,
разбор — в блоке «ПРОВАЛЫ» (имя ситуации, вход, ответ, причина).

**Общая ошибка `UnicodeEncodeError`** — Windows-консоль в cp1252 не может
напечатать русский. Уже пофикшено (`reconfigure` + `PYTHONUTF8=1`). Если
повторится — проверь, что эти правки на месте.

## 📦 requirements-ci.txt

Отдельный файл — **только то, что нужно для CI**:

- `filelock`, `psutil`, `pyperclip`, `Pillow`
- `numpy` (нужен `prosody.py` и `vad.py`)
- `pytest`, `pytest-asyncio`

**Чего нет:**
- `piper-tts`, `faster-whisper`, `sounddevice`, `vosk`, `winrt-*` — на сервере нет звука.
- `pycaw`, `screen-brightness-control` — Windows-специфичные, тяжёлые.
- `pyautogui`, `pygetwindow`, `keyboard`, `mouse` — GUI.

**Почему:** CI ускоряется с ~5 мин до ~40 сек. И не падает на «нет звука».

## ➕ Как добавить шаг

В `.github/workflows/test.yml`:

```yaml
      - name: Мой новый шаг
        run: python my_script.py
```

Пуш → GitHub сам подхватит.

## 🎨 Бейдж в README

```markdown
[![tests](https://github.com/USER/REPO/actions/workflows/test.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/test.yml)
```

Замени `USER/REPO` на свой.

## 📋 Что проверять **локально** перед пушем

Чтобы CI не падал — прогони у себя:

```bat
check_all.bat                     :: всё сразу (4 шага) + компактный итог
python check_syntax.py
python -m pytest tests/ -q
python tests/test_intents.py
python tests/stress_intents.py
```

Все шаги зелёные → **CI тоже пройдёт**.

## 🆕 Пути в CI

**`jarvis/paths.py`** использует `%PROGRAMDATA%` и `%APPDATA%`.
На GitHub Actions они **стандартные** — пути разрешатся в:
- `PROGRAM_DIR` → `C:\ProgramData\Phoenix\` (ASCII).
- `USER_DIR` → `C:\Users\runneradmin\AppData\Roaming\Phoenix\` (ASCII — повезло).

**Плюс:** CI **не тестирует** Vosk/Whisper/Piper — они в
`requirements-ci.txt` **не стоят**. Значит `paths.py` вызывается,
но **модели не качаются**.

## 🚀 Авторелиз — release.yml (13.10.2026)

Раньше это было «в планах», теперь работает: пуш тега `v*` собирает
`Феникс.exe` + `Феникс_Setup.exe` и создаёт GitHub Release.

**Когда запускается:**

| Что | Результат |
|---|---|
| `git push origin v1.0.2` (тег `v*`) | сборка + **GitHub Release** с двумя файлами |
| Actions → **build-release** → Run workflow | только сборка, файлы в артефактах |

**Что делает по шагам:**

1. Checkout, Python 3.11, кэш pip.
2. `pip install -r requirements-dev.txt Pillow` — PyInstaller для `.exe`,
   Pillow для BMP-баннеров установщика. **Зависимости проекта не ставятся:**
   `Феникс.exe` — это `launcher.py`, а он на чистой стандартной библиотеке,
   тяжёлые пакеты (vosk, faster-whisper, torch…) ставит сам при первом запуске.
3. `choco install innosetup --no-progress -y` — Inno Setup 6 через Chocolatey
   (на раннере он есть; `ISCC.exe` появляется в `PATH`).
4. `python scripts\build_setup.py --version <версия из тега>` — иконка →
   баннеры → `Феникс.exe` → `Феникс_Setup.exe`.
5. `actions/upload-artifact@v4` — оба файла (доступны всегда, даже на теге).
6. На теге — `gh release create "$TAG" dist\Феникс_Setup.exe Феникс.exe
   --generate-notes`: релиз с авто-заметками и двумя вложениями.

**Версия.** Из тега `v1.0.2` берётся `1.0.2` и уходит в Inno Setup как
`/DMyAppVersion=1.0.2` → `AppVersion` установщика и `ProductVersion` в
свойствах файла. Локально то же самое:

```bat
python scripts\build_setup.py --version 1.0.2
```

**Как выпустить релиз:**

```bat
git tag v1.0.2 -m "Феникс 1.0.2"
git push origin v1.0.2
```

Дальше GitHub собирает и публикует сам: файлы появятся на вкладке
**Releases**, копия — в артефактах запуска Actions.

**Если упало:**

| Симптом | Причина / что делать |
|---|---|
| `не найден ISCC.exe` | Chocolatey не поставил Inno Setup → смотри шаг `Install Inno Setup 6` |
| `no files found matching "packs\*"` | из репозитория пропал файл поставки → `git ls-files packs` |
| Ошибка прав при создании релиза | в workflow должно быть `permissions: contents: write` |
| PyInstaller не собрал `.exe` | лог шага `Сборка Феникс.exe + Феникс_Setup.exe` |

**Почему `system_caps.json` в CI не генерируется:** `scripts/check_caps.py`
требует `pycaw` и `screen-brightness-control`, которых на раннере нет (нет
звуковой карты и дисплея). `build_setup.py` это видит и **пропускает** шаг —
файл необязателен (в `installer.iss` он с `skipifsourcedoesntexist`).

**Локально сборка тоже автоматизирована** — одна команда собирает `.exe`
и установщик (см. `scripts/build_setup.py`):

```bat
python scripts\build_setup.py
```

**Проверено локально:** сборка с `--version 1.0.2` даёт установщик с
`ProductVersion 1.0.2`, без флага — дефолт `1.0.0` из `installer.iss`
(`#ifndef MyAppVersion`). Сам workflow валидирован по YAML и по прогону
всех его команд на локальной машине; первый настоящий запуск на GitHub
произойдёт при пуше тега.

## 📌 Полезное

- **Бейдж релиза:**
  ```markdown
  [![Release](https://img.shields.io/github/v/release/USER/REPO)](https://github.com/USER/REPO/releases)
  ```
- **Бейдж скачиваний:**
  ```markdown
  [![Downloads](https://img.shields.io/github/downloads/USER/REPO/total)](https://github.com/USER/REPO/releases)
  ```
- **Workflow файл:** `.github/workflows/test.yml`.