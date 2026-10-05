# CI — что это и как с ним жить

## 🎯 Что такое CI

CI = Continuous Integration = автоматическая проверка кода при каждом push.

GitHub Actions запускает виртуалку с Windows, ставит Python, зависимости,
прогоняет тесты. Через ~40 секунд ты видишь: ✅ или ❌.

**Зачем:** ловит регрессии, пока ты спишь. Не нужно помнить про тесты —
GitHub запускает их сам.

## 📁 Где лежит

`.github/workflows/test.yml` — инструкция для GitHub.

## 🔍 Что делает

1. Checkout — скачивает код.
2. Setup Python 3.11 + кэш pip.
3. `pip install -r requirements-ci.txt` — облегчённые зависимости.
4. `python check_syntax.py` — синтаксис.
5. `python -m pytest tests/ -q` — юнит-тесты.
6. `python test_intents.py` — интент-тесты без флагов.

`PYTHONUTF8=1` — глобально на весь job, страховка от cp1252.

## 🚀 Как смотреть результат

1. Открой репозиторий на GitHub.
2. Вкладка **Actions** (сверху).
3. Последний запуск — ✅ или ❌.
4. Кликни → увидишь шаги и логи.

## 🔧 Если упало

**Шаг `Check syntax`** — синтаксис где-то сломан. Открой лог, найди файл и строку.

**Шаг `pytest`** — юнит-тест упал. Лог покажет какой.

**Шаг `Intent tests`** — интент-тест упал. Логи в артефактах Actions или
локально `logs/test_intents.log`.

**Общая ошибка `UnicodeEncodeError`** — Windows-консоль в cp1252 не может
напечатать русский. Уже пофикшено (`reconfigure` + `PYTHONUTF8=1`). Если
повторится — проверь, что эти правки на месте.

## 📦 requirements-ci.txt

Отдельный файл — **только то, что нужно для CI**:

- `filelock`, `num2words`, `psutil`, `pyperclip`, `Pillow`
- `pytest`, `pytest-asyncio`

**Чего нет:**
- `piper-tts`, `faster-whisper`, `sounddevice`, `vosk`, `winrt-*` — на сервере нет звука
- `pycaw`, `screen-brightness-control` — Windows-специфичные, тяжёлые
- `pyautogui`, `pygetwindow`, `keyboard`, `mouse` — GUI

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

Замени `USER/REPO` на свой. Вставь в начало README.