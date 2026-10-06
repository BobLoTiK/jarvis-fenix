📋 План развития «Феникс»

Форк [jsays12/jarvis](https://github.com/jsays12/jarvis).
Коммиты до июня 2026 — от оригинала, с октября 2026 — мои изменения.

**Сложность:** 🟢 легко · 🟡 средне · 🔴 сложно
**Статус:** ✅ готово · 🚧 в работе · ⏸ отложено · ❌ не начато

---

## 📊 СВОДКА

| Категория | Всего | ✅ Закрыто | ❌ Осталось |
|---|---|---|---|
| 🔴 Критичные баги | 2 | 0 | 2 |
| 🟡 Серьёзные баги | 9 | 0 | 9 |
| 🟢 Мелкие баги | 4 | 0 | 4 |
| 🎁 История (закрыто) | 13 | 13 | — |
| 🎁 Обновления технологий | 7 | 1 | 6 |
| 🆕 Фичи (бесплатные) | 13 | 0 | 13 |
| 🆕 Знакомство | 7 | 0 | 7 |
| 🆕 Стресс-тест | 3 | 0 | 3 |
| 🆕 Мои команды | 9 | 0 | 9 |
| 🆕 Фичи (платные, потом) | 6 | 0 | 6 |
| **ИТОГО** | **73** | **14** | **59** |

**Время:** Этап 0 (обновления) — 1 ч · Этап 1 (баги) — 5 ч · Этап 1.5 (знакомство) — 3.5 ч · Этап 1.6 (стресс-тест) — 2 ч · Этап 1.7 (мои команды) — 6.5 ч · Этап 2 (облако бесплатно) — 12 ч · Этап 3 (облако платно) — 8.5 ч

---

## 🏗 АРХИТЕКТУРА РЕЖИМОВ РАБОТЫ

Феникс поддерживает **три режима**, пользователь выбирает в GUI или config.

### 🏠 Local (по умолчанию)

| Компонент | Решение | Интернет |
|---|---|---|
| Wake-слово | Vosk small | ❌ |
| STT | Whisper small CPU | ❌ |
| LLM | Qwen 2.5 3b/7b (Ollama) | ❌ |
| TTS | Piper (ruslan/dmitri/irina/denis) | ❌ |
| Погода | Кэш 24 ч | почти не нужен |

### 🌐 Hybrid (нужен интернет)

| Компонент | Решение |
|---|---|
| Wake-слово | Vosk small |
| STT | Whisper **large-v3-turbo** на GPU |
| LLM | Qwen 2.5 **14b/32b** (Ollama) |
| TTS | Piper |
| Погода | Real-time |

### ☁️ Cloud (нужен интернет + ключ Groq — бесплатно)

| Компонент | Решение | Стоимость |
|---|---|---|
| Wake-слово | Vosk small (локально) | 0 |
| STT | **Groq Whisper large-v3** | **бесплатно** |
| LLM | **Groq Llama 3.3 70B** | **бесплатно** |
| TTS | **Edge TTS** (Microsoft) | **бесплатно** |
| Погода | Real-time | 0 |

**Fallback:** при ошибке облака — откат на local.

### 💎 Premium (потом — ключи OpenAI, Fish Audio)

- **LLM:** GPT-4o, Claude 3.5, DeepSeek.
- **STT:** Whisper API, Deepgram.
- **TTS:** Fish Audio (клон голоса), ElevenLabs.
- **Биллинг:** видно, сколько потратил.

**Отложено.**

---

## ✅ ЗАКРЫТО — 13 багов (история)

| № | Баг | Где | Как закрыт |
|---|---|---|---|
| №1 | `profile._current` гонка | `profile.py` | `threading.Lock` в `current()`/`switch()` |
| №2 | Маша видит диалог Максима | `intents.py` + `profile.py` | `profile.subscribe()` + `_on_profile_switch` |
| №3 | `_awaiting_until` после `say()` | `main.py` | Перенесено **до** `say()` |
| №6 | `CANCEL` не первым | `intents.py` | Перенесено в начало `_handle_single` |
| №8 | `any([...])` в `_do_close` | `intents.py` | Генератор + early exit |
| №14 | `brain.parse` без `.strip()` | `brain.py` | `.strip().lower()` для action и steps |
| №20 | TTS накладывается (2–3 голоса) | `tts.py` | Per-call stop-token вместо общего `_stop_flag` |
| №21 | `_profile_fast` не матчит из GUI | `intents.py` | `cmd = normalize(cmd)` в начале `handle()` |
| №24 | Светлая тема ломала GUI | `gui.py` | `PALETTES` + пересборка UI на лету |
| №24.5 | Системная тема не автоопределялась | `gui.py` | `_detect_system_theme()` через реестр Windows |
| №25 | `mic_watchdog` спамил | `main.py` | Одно предупреждение за сессию + пик ≥ 50 |
| №25.5 | Микрофон не проверить из GUI | `gui.py` + `stt.py` | Вкладка «Микрофон» + прогресс-бар + кнопка теста |
| — | Flet 1.x API (`ElevatedButton` → `Button`) | `gui.py` | `ft.Button` с `content=` и `style=` |

---

## 🔴 КРИТИЧНЫЕ БАГИ — 2

### №10 — Порядок импортов глушится

**Файл:** `jarvis/main.py` (начало `main()`)
**Симптом:** `except ImportError: pass` глушит ошибку. Если `faster_whisper` не установлен — `winrt` загрузится первым → access violation на Windows.
**Фикс:** логировать отсутствие каждого модуля явно.
**Время:** 10 мин.

### №11 — `Vosk.Reset()` не откатывает контекст

**Файл:** `jarvis/stt.py`, `Listener.flush()`
**Симптом:** после `Reset()` Vosk может выдать «остаток» фразы. В barge-in просачивается обрывок.
**Фикс:** прогнать 0.5 сек тишины через `AcceptWaveform` после `Reset()`.
**Время:** 30 мин.

---

## 🟡 СЕРЬЁЗНЫЕ БАГИ — 9

### №5 — Факты путают `parse()`

**Файл:** `jarvis/brain.py`, `_system_with_context`
**Симптом:** `_chat` (JSON-разбор) получает `learning.build_context()` с фактами. Маленькие модели (3b) путаются.
**Фикс:** в `_chat` не подмешивать контекст. Только `chat`/`chat_stream` — с контекстом.
**Время:** 20 мин.

### №7 — `tasks.find` без `_lock`

**Файл:** `jarvis/tasks.py`
**Симптом:** `find()` вызывается внутри `remove`/`mark_done` под локом, но сам lock не берёт.
**Фикс:** `threading.Lock` вокруг `find`.
**Время:** 15 мин.

### №9 — `weather._CACHE` без lock

**Файл:** `jarvis/weather.py`
**Симптом:** глобальный `dict` без защиты. `_CACHE[key] = (now, data)` — две операции.
**Фикс:** `threading.Lock` вокруг `_CACHE`.
**Время:** 15 мин.

### №12 — `learning.add_fact` не проверяет `ok`

**Файл:** `jarvis/learning.py`
**Симптом:** `profile.set` при битом JSON вернёт `False`, но `add_fact` вернёт `True`.
**Фикс:** `if not ok: return False`.
**Время:** 10 мин.

### №13 — `Config.update` без `if ok`

**Файл:** `jarvis/config.py`
**Симптом:** оповещает подписчиков даже при упавшем `save`.
**Фикс:** оповещать только при `ok`.
**Время:** 15 мин.

### №15 — «включи музыку» → `open_app`

**Файл:** `jarvis/intents.py`, `_open_fast`
**Симптом:** regex ловит «включи музыку» раньше, чем `play_pause`.
**Фикс:** отдельное правило «включи музыку / плей / пауза» **до** `_open_fast`.
**Время:** 30 мин.

### №16 — `_debug_fast` не тот буфер

**Файл:** `jarvis/intents.py`, `_debug_fast`
**Симптом:** «что ты слышал» показывает `IntentHandler._recent_phrases`, а не `stt.Listener.recent_phrases`.
**Фикс:** пробросить `Listener.recent_phrases` в `IntentHandler`.
**Время:** 20 мин.

### №17 — Макрос забивает стек отмены

**Файл:** `jarvis/intents.py`, `_execute_steps`
**Симптом:** `history.push` вызывается на каждый шаг макроса.
**Фикс:** пушить один агрегированный item `"macro"`.
**Время:** 30 мин.

### №18 — `profiles/maksim.json` — мусор

**Файл:** `profiles/maksim.json` (в корне)
**Симптом:** остаток до мультипрофиля. Миграция его не подхватывает.
**Фикс:** удалить или расширить `_migrate_old`.
**Время:** 5 мин.

---

## 🟢 МЕЛКИЕ БАГИ — 4

### №19 — Нумерация этапов в README/PLAN

**Файлы:** `README.md`, `PLAN.md`
**Фикс:** синхронизировать (главная — PLAN).
**Время:** 15 мин.

### №22 — `describe_weather` — падежи

**Файл:** `jarvis/weather.py`
**Симптом:** «Погода в **Казань**».
**Фикс:** переформулировать: «Сейчас в городе Казань, Россия…».
**Время:** 15 мин.

### №23 — LLM vs `profile.get("name")` рассинхрон

**Файл:** `jarvis/intents.py`
**Симптом:** LLM отвечает «не знаю», TTS говорит «Вас зовут …».
**Фикс:** разобраться с потоком `chat_stream`.
**Время:** 20 мин.

---

## 🎁 ОБНОВЛЕНИЯ ТЕХНОЛОГИЙ — 7

### ✅ О1 — pip-пакеты (закрыто)

- `vosk 0.3.45`
- `faster-whisper 1.2.1` + `ctranslate2 4.8.2`
- `piper-tts 1.8.0`

### ❌ О2 — Whisper-модель (5 мин)

`config.json`: `"whisper_model": "coriollon/whisper-large-v3-turbo-russian"`.

### ❌ О3 — `check_cpu()` в `check_caps.py` (20 мин)

Определяет категорию CPU (`weak` / `normal` / `strong`) → рекомендация `medium` / `high` для Piper. **Без личных данных** (только цифры).

### ❌ О4 — `tts_voice_quality` в config (10 мин)

`"medium"` / `"high"`.

### ❌ О5 — `tts._init_piper` — quality + fallback (15 мин)

Путь: `ru/ru_RU/{voice}/{quality}/ru_RU-{voice}-{quality}.onnx`. Fallback на medium.

### ❌ О6 — GUI RadioGroup «Качество голоса» (15 мин)

В `_build_settings_tab`.

### ❌ О7 — README + config.example.json (10 мин)

Документация + дефолты.

---

## 🆕 ФИЧИ — бесплатно (13)

### Режимы работы (Ф1–Ф13)

| # | Фича | Время |
|---|---|---|
| Ф1 | `operation_mode` в config | 1 ч |
| Ф2 | `cloud/base.py` (ABC) | 30 мин |
| Ф3 | `cloud/groq_llm.py` (Llama 3.3 70B) | 1.5 ч |
| Ф4 | `cloud/groq_stt.py` (Whisper large-v3) | 1 ч |
| Ф5 | `cloud/edge_tts.py` (Microsoft) | 1.5 ч |
| Ф6 | `cloud/router.py` | 30 мин |
| Ф7 | Рефактор `brain.py` под `LLMProvider` | 1 ч |
| Ф8 | Рефактор `stt.py` под `STTProvider` | 1 ч |
| Ф9 | Рефактор `tts.py` под `TTSProvider` | 1.5 ч |
| Ф10 | GUI вкладка «Режим работы» | 1 ч |
| Ф11 | Fallback cloud → local | 30 мин |
| Ф12 | requirements: `edge-tts`, `pydub` | 5 мин |
| Ф13 | README — «Режимы работы» | 20 мин |

**Итого:** ~12 ч.

---

## 🆕 ЗНАКОМСТВО (7)

Феникс при первом запуске (или при создании нового профиля) проводит диалог — 7 вопросов. Строит **персону** в `profiles/<user>/profile.json`:

```json
{
  "name": "...",
  "persona": {
    "address": "брат",
    "style": "шутливый",
    "answer_length": "short",
    "profanity": true,
    "humor": "чёрный",
    "formality": "ты"
  },
  "onboarding_done": true
}
