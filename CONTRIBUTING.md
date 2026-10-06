# Как контрибьютить в Феникс

Документ для себя-будущего и для LLM, которая помогает с проектом.

## 🎯 Главное правило

**Не добавляй костыли.** Если решение «работает, но выглядит грязно» —
это не решение. Лучше потратить час сейчас, чем три — через месяц.

## 📁 Структура

```
jarvis/             — пакет
  reply.py          — тип Reply (text | stream)
  intents.py        — разбор команд, быстрые правила + LLM
  main.py           — точка входа, Jarvis, barge-in
  brain.py          — Ollama: parse() и chat_stream()
  config.py         — Config в памяти + подписки
  config_manager.py — атомарная запись
  tts.py            — Piper / XTTS / WinRT / SAPI + per-call token
  stt.py            — Vosk + Whisper + ring buffer
  gui.py            — Flet GUI + PALETTES + _detect_system_theme()
  ...

tests/              — pytest-тесты
test_intents.py     — интент-тесты (без микрофона)
check_syntax.py     — синтаксис всех .py
snapshot.py         — сборка SNAPSHOT.md

packs/              — JSON-паки команд
scripts/            — утилиты (mics, wakebench, build_exe)
.github/workflows/  — CI
```

## 📝 Правила кода

1. **Не читай `config.json` напрямую** — используй `config.get()` из объекта `Config`.
2. **Не пиши в `config.json` напрямую** — только `Config.set()` или `config_manager.save()`.
3. **Не плоди глобальное состояние** — кроме `Config._GLOBAL`.
4. **Нормализация (города, валюты, паков) — задача LLM.** Не добавляй словари синонимов в код без нужды.
5. **Логи в `actions.log`** — главный инструмент отладки.
6. **Не выбрасывай ошибки в `errors.log`** — это сигнал, что что-то сломалось, разбирайся.
7. **`test_intents.py`** — первое, что запускаешь после правки `intents.py`, `brain.py`, `actions.py`.
8. **`normalize(cmd)` в `IntentHandler.handle()`** — единая точка нормализации для GUI и голоса.
9. **Per-call stop-token в `tts.py`** — не используй общий `_stop_flag`. Каждый вызов `play_async` / `speak_stream` создаёт свой токен.
10. **`PALETTES` в `gui.py`** — две палитры (dark/light), `_detect_system_theme()` для системной темы через реестр Windows.
11. **`ft.Button`** вместо `ft.ElevatedButton` / `ft.TextButton` — в Flet 1.x их удалили.

## 🔒 Правила безопасности

**Никогда не упоминай в публичных файлах** (`
