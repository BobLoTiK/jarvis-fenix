# AGENTS — правила работы с Фениксом

## Цель и навигация

JASTIN — целевое видение Феникса от работодателя. Реализуем максимально,
с небольшими обоснованными оговорками. Различие нынешнего стека и цели —
задача перехода, не причина исключать биометрию, SDK, память, router или GUI.
Изменения требований и конфликтующие технологии согласовывать.

- Вход: [START_HERE](START_HERE.md), [PROMPT](PROMPT.md).
- Факты/непроверенное: [PROJECT](PROJECT.md).
- Цель/очередь: [PLAN](PLAN.md), [NEXT_STEPS](docs/NEXT_STEPS.md).
- Детали цели: [разбор](docs/PHOENIX_JASTIN_RECONCILIATION.md),
  [оригиналы](docs/reference/README.md).
- Устройство кода: [ARCHITECTURE](ARCHITECTURE.md).
- Проверки: [текущий отчёт](docs/HANDOFF_VALIDATION.md),
  [тестовый справочник](tests/README.md), [приёмка](docs/ACCEPTANCE_CHECKLIST.md).

## Среда и фактическая база

Target: Windows x64 / Python 3.11.9 / .venv311; Flet 1.0.x.
VAD → Vosk → опциональный faster-whisper; Ollama локально;
auto TTS Silero → Piper → SAPI. WinRT TTS удалён, WinRT Media Control сохранён.
Обычный optional AEC — Piper; ручная PCM-диагностика Piper/Silero;
SAPI без PCM — метаданные. Последний пакет ещё не принят пользователем.
Linux/Python 3.13 пригоден для portable tests, не доказывает Windows runtime.

## Основные контракты

- IntentHandler.handle(raw) → Reply(text | stream, allow_nonverbal=False).
  Сохранять safety до TTS/истории и finalize_stream; отмена не сохраняет
  выдуманно произнесённую часть ответа. Сомнительный ASR → повтор, не действие.
- Не обходить pending password/question. parse action=none — не отправлять
  на вторую догадку в свободный чат. Observer opt-in, не учится на ассистенте.
- Числовые слоты language.analyze_command до потери исходной пунктуации.
  prepare_text уже обрабатывает числа/даты/единицы — не создавать второй слой.
- cmd_lock — команды GUI/голоса; _say_lock — речь/таймеры/уведомления.
  Per-call stop-token, wait_end возвращает bool; нет второго плеера/capture.
- Flet меняется в GUI owner через очередь. Vosk API — только listener owner.
  UIA — STA/COM и lock. Epoch/profile guards отсекают поздние callbacks.
- Nonverbal opt-in в Speaker: один PCM/общий token/cooldown, без отдельного
  проигрывателя. SAPI без PCM-реакций. Output/AEC получают итоговый mixed PCM.
- Config/profile пишутся атомарно через существующие интерфейсы, expected_values/
  expected_profile сохраняются. Ошибка записи не становится успехом; черновики
  не пишутся на каждый ввод. Пути только через paths.py.
- Риск всех custom/pack шагов проверяется до исполнения; секреты не логировать.
  Текущий SHA-256 пароль не выдавать за современную KDF; усиление — отдельная задача.
- RAG не найден/сломался — не раскрывать весь профиль. Смена LLM не стирает знания.

Эти контракты могут развиваться в целевой архитектуре, но не исчезать молча.
Subprocess — crash isolation, не обещание OS sandbox для недоверенного кода.

## Изменения

Один вертикальный срез, сначала чтение владельца подсистемы и соседних тестов.
Сейчас основной ASR/GUI не заменять попутно; целевые адаптеры/миграции — этапы
R2/R5. Vosk сохраняется как минимум wake/fallback. Новые зависимости/модели,
сеть и миграция данных — явно, с целью, лицензией, проверкой и rollback.
Без маскировки дефекта случайным порогом, запрещённым словом или fake success.

UTF-8 без BOM, CRLF для изменяемых Windows-текстов; shell hook остаётся LF.
Не нормализовать весь репозиторий. Сохранять MIT/attribution jsys12 и лицензии
ресурсов. Не включать config.json, profiles, историю, models, venv, logs,
локальные аудиозаписи и секреты в Git/ZIP/snapshot.

## Проверки и передача

Целевые команды Windows, из корня:

```powershell
.\.venv311\Scripts\python.exe check_all.py
.\.venv311\Scripts\python.exe snapshot.py
.\.venv311\Scripts\python.exe snapshot.py --check
.\.venv311\Scripts\python.exe scripts/build_setup.py --check
```

check_all: syntax → pytest → intent runner → stress runner.
Linux portable: PYSTRAY_BACKEND=dummy, исключаются два winreg-модуля
(test_browser_target.py/test_window_targets.py); точная команда в отчёте.
Опциональные native/model тесты могут быть skipped — перечислить ограничения.
Audio regression prepare/run — отдельный opt-in, без реальных побочных эффектов;
BLOCKED не считать pass. WAV и транскрипты остаются вне архива.

После шага: регрессии → актуальные PROJECT/PLAN/руководство/CHANGELOG →
сгенерировать snapshot.py → --check → проверить состав/применение ZIP к копии.
Не читать/печатать весь SNAPSHOT при доступных исходниках. README — витрина,
не журнал патчей. Не выполнять commit/push/tag без разрешения; не выдумывать их.
В handoff назвать выполненное, файл, способ применения и непроверенные границы.
