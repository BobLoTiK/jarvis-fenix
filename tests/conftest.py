"""Настройки pytest для папки tests/.

tests/ — единственное место, где живут проверки, но не всё здесь
pytest-тесты:

  * ``test_*.py``        — обычные pytest-тесты (собираются автоматически);
  * ``test_intents.py``  — скрипт-раннер на своём харнесе (создаёт
                           IntentHandler, пишет logs/test_intents.log).
                           pytest его НЕ собирает — см. collect_ignore;
  * ``stress_intents.py``— стресс-тест на 100 ситуаций, тоже скрипт-раннер.
                           pytest не подхватывает его сам (нет префикса
                           ``test_``), запускается вручную / из check_all.bat;
  * ``manual/``          — ручные прогоны (микрофон, UIA, ONNX),
                           запускаются вручную.

Без collect_ignore pytest импортировал бы test_intents.py в общий прогон
и тянул бы за собой IntentHandler там, где он не нужен.
"""

collect_ignore = ["test_intents.py"]
