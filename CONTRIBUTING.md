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
  tts.py            — Piper / XTTS / WinRT / SAPI
  stt.py            — Vosk + Whisper
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

## 🧪 Тесты

### Локально

```bat
python check_syntax.py
python -m pytest tests/ -q
python test_intents.py
```

### С флагами

```bat
python test_intents.py --network        # + тесты погоды/курса
python test_intents.py --llm            # + тесты с LLM (нужна Ollama)
python test_intents.py --llm --network  # всё
python test_intents.py --voice          # с озвучкой
python test_intents.py -k weather       # только тесты со словом 'weather'
```

### В CI

GitHub Actions запускает при каждом push:
- `check_syntax.py`
- `pytest tests/`
- `test_intents.py` — **без флагов** (без LLM, без сети, без озвучки).

Это значит: **новые тесты должны работать без LLM и без сети**. Если тест
требует сеть — помечай `requires_network=True`. Если LLM — `requires_llm=True`.

## 🏷️ Коммиты

Пиши так, чтобы через полгода понять без `git diff`:

```
День 3: Reply, CI, тесты с моками

- jarvis/reply.py — новый тип
- intents.py: handle() возвращает Reply
- ...
```

Одна строка — суть. Тело — список изменений.

## ✅ Чеклист перед коммитом

- [ ] `python check_syntax.py` — все файлы OK
- [ ] `python -m pytest tests/ -q` — все тесты passed
- [ ] `python test_intents.py` — 20/20 (без флагов)
- [ ] Если добавил фичу — обнови `README.md`
- [ ] Если сломал API — обнови `ARCHITECTURE.md` и `SNAPSHOT.md`
- [ ] Закоммить, запушить, посмотреть CI (✅ или ❌)