# Тесты Феникса

Здесь собраны **все** проверки проекта. В корне остались только точки
входа: `check_all.bat` (запускает всё) и `check_syntax.py` (проверка
синтаксиса — им пользуется и CI, и `install.bat`).

## Карта

| Что | Где | Как запускать |
|---|---|---|
| Юнит-тесты (pytest) | `tests/test_*.py` | `python -m pytest tests/ -q` |
| Интент-тесты (39 сценариев) | `tests/test_intents.py` | `python tests/test_intents.py [--llm] [--network] [--voice] [-k фильтр]` |
| Стресс-тест (100 ситуаций) | `tests/stress_intents.py` | `python tests/stress_intents.py` |
| **Всё сразу** | — | `check_all.bat` (или `python check_all.py`) |
| Ручные прогоны | `tests/manual/` | вручную: микрофон / браузер / ONNX |

## Правила

* **Новый pytest-тест** — файл `tests/test_<модуль>.py`, функции `test_*`.
  Это единственный вид, который подхватывает `pytest tests/`.
* **Ручной прогон** (нужен микрофон, браузер, железо) — `tests/manual/`
  и имя **без** префикса `test_` (например `vad_live.py`), чтобы pytest
  не запускал его случайно. В начале файла — `sys.path.insert` до корня
  проекта, иначе `import jarvis` не найдётся.
* **Скрипт-раннер** (свой харнес, многошаговые прогоны, свои логи) —
  имя без префикса `test_` либо запись в `collect_ignore` в
  `tests/conftest.py` (так исключён `test_intents.py`, имя которого
  историческое и упоминается в документации).

## Логи

* `logs/test_intents.log` — подробный лог интент-тестов;
* `logs/stress_intents.log` — подробный лог стресс-теста;
* `logs/check_all/` — вывод шагов `check_all.bat` по шагам.

## См. также

* `CONTRIBUTING.md` — что запускать перед коммитом;
* `.github/workflows/test.yml` — как это гоняется в CI;
* `CI.md` — разбор CI.
