# AGENTS.md — навигация для помощника по «Феникс»

Актуализировано 15.10.2026. Сначала нужный раздел `PROJECT.md`, затем поиск
по файлам и чтение небольшого диапазона. Не загружать целиком `SNAPSHOT.md`:
это генерируемый контекст, а не место правки кода. Историю не выдавать за текущий статус.

## Среда и запуск

Windows, Python 3.11.9, `.venv311`, Flet 1.0.x, Vosk + Whisper, Ollama.
TTS: Silero/Piper/WinRT/SAPI. Python 3.13/3.14 не брать для Windows/Vosk-runtime.

```powershell
.\.venv311\Scripts\python.exe check_all.py
.\.venv311\Scripts\python.exe -m pytest tests/ -q
.\.venv311\Scripts\python.exe tests/test_intents.py
.\.venv311\Scripts\python.exe tests/stress_intents.py
.\.venv311\Scripts\python.exe check_syntax.py
.\.venv311\Scripts\python.exe snapshot.py
.\.venv311\Scripts\python.exe snapshot.py --check
.\.venv311\Scripts\python.exe launcher.py
```

41 интент-сценарий (34 без LLM/сети), 102 стресс-сценария.
Число pytest не фиксировать как вечную константу; свежая проверка — `tests/README.md`.
`check_all` — четыре шага; workflow CI отдельно требует актуальный snapshot.

## Карта

| Модуль | Роль |
|---|---|
| `jarvis/main.py` | голосовой цикл, ASR gate, cmd_lock, _say_lock, barge-in |
| `jarvis/gui.py` | Flet, вкладки, очередь событий |
| `jarvis/intents/` | handler, pipeline, fast-правила, исполнение |
| `jarvis/language/` | числовые слоты команд, чтение чисел/римских цифр, морфология |
| `jarvis/recognition.py`, `stt.py`, `vad.py` | уверенность ASR, Vosk/Whisper, VAD |
| `jarvis/brain.py` | Ollama parse/chat, системные правила |
| `jarvis/memory_context.py`, `learning.py`, `vectormem.py` | отбор личных фактов и RAG |
| `jarvis/observer.py` | извлечение прямых утверждений пользователя; opt-in |
| `jarvis/tts.py`, `tts_engines/` | Speaker и движки, per-call token |
| `jarvis/audio_output.py`, `nonverbal.py` | единый PCM-микшер и политика реакций |
| `assets/nonverbal/` | четыре CC0 WAV + источники/лицензия/хеши |
| `jarvis/mood.py`, `prosody.py`, `persona.py` | состояние, эвристика голоса, стиль |
| `jarvis/safety.py` | фильтр ответов перед TTS/историей стрима |
| `jarvis/uia.py`, `actions.py` | COM, окна, браузеры, системные действия |
| `jarvis/paths.py`, `config.py`, `profile.py` | пути, настройки, профили/кэш |
| `snapshot.py`, `check_all.py`, `scripts/build_setup.py` | снимок, проверки, выпуск |

## Контракты, которые легко сломать

- `IntentHandler.handle(raw)` → `Reply(text | stream, allow_nonverbal=False)`.
  Для стрима вызвать `finalize_stream()` после завершения безопасной озвучки.
- Не удалять исходную пунктуацию до `language.analyze_command()`.
  `normalize()` не заменяет семантический разбор чисел; пароли проходят раньше.
- Сомнительную расшифровку не передавать handler/Observer/истории; запросить повтор.
  Отказ JSON-parser (`none`) не отправлять в чат на вторую догадку.
- `learning.build_context(query=...)` и `memory_context.select_memory()` ограничивают
  личные факты. Пустой/сломанный RAG не означает «отправь всё».
- Observer не учится на репликах ассистента, выключен без согласия.
- Nonverbal принадлежит Speaker: opt-in, только помеченный диалог, одна попытка
  на ответ, общий cooldown. Silero/Piper/WinRT используют один WAV-output callback;
  SAPI остаётся без PCM-реакций. Никаких дополнительных проигрывающих потоков.

## Конвенции и безопасность

UTF-8 без BOM, CRLF. Не менять кодировки всего проекта случайной командой.
Config читать через `get`, писать через `set`/config_manager, данные — атомарно.
Пути только через `paths.py`: ASCII PROGRAM_DIR для моделей, USER_DIR для личного.
Flet главный поток; cmd_lock и _say_lock сохранять; Vosk только listener-поток.
Stop-token per-call; `wait_end` возвращает bool. UIA STA/COM под lock.
Опасность custom/pack-макроса проверять до первого шага. Пароли не логировать.
Личные JSON, модели, окружения, логи, build/dist не коммитить.
Новые зависимости не добавлять без согласования; `num2words`/`pymorphy3` уже согласованы.
Лицензию/attribution jsys12 не удалять. CC0-активы хранить вместе с происхождением.

## После правки

Добавить регрессии, прогнать доступные проверки, явно назвать пропуски и платформу.
Не называть mock/headless-проверку живым Windows-аудиотестом.
Обновить соответствующие руководства и PROJECT/PLAN/CHANGELOG, затем сгенерировать
SNAPSHOT. README оставлять витриной проекта: не вставлять в начало датированные
обновления/отчёты; возможности описывать в тематических разделах, историю — в CHANGELOG. Внешний graphify-отчёт без запуска graphify не объявлять пересобранным.
Один фокус за раз: аудиорегрессии → GUI (функции/удобство → оформление)
→ проверенные исправления/самообучение
→ память → измеряемая оптимизация. Облако/Telegram/Hermes/MCP/VLM — дальний бэклог.
`intents/clarification.py` использует существующий `_pending_question`: target/time/unit,
30 с по monotonic, три неудачных ответа. Не считать это универсальным диалоговым
планировщиком или дообучением модели. Проверенный слот возвращается в pipeline;
custom/password остаются обязательными. Pipeline: cancel → pending → onboarding
→ correction → password → memory → clipboard → modes → compound → clarification
→ fast → llm. Ответы на слоты не направлять в Observer. Метрики handler/stages
не включают STT/генерацию стрима/TTS и не содержат текст или пароль.


## Аудиорегрессии

Отдельный opt-in CLI `scripts/audio_regression.py prepare|run`, инструкции в
`tests/audio/README.md`. Обычный pytest не запускает модели/микрофон/TTS.
File-mode Listener и микрофон используют один `_consume_audio`; не подменять
ASR ожидаемым текстом сценария, не форсировать FinalResult ради зелёного теста.
Hybrid/VAD fallback или отсутствующая модель = BLOCKED/2, а не pass/skip.
Не расширять ограниченный sandbox до выполнения реальных действий. Не включать
WAV/транскрипты/модели в ZIP/Git/snapshot. GUI — следующий отдельный блок, ещё не сделан.
