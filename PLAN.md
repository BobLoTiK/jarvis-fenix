📋 План развития «Феникс»
Форк jsays12/jarvis.
Коммиты до июня 2026 — от оригинала, с октября 2026 — мои изменения.

Сложность: 🟢 легко · 🟡 средне · 🔴 сложно
Статус: ✅ готово · 🚧 в работе · ⏸ отложено · ❌ не начато

🔴 ЭТАП 0 — Архитектурный рефакторинг (фундамент) — ✅ ЗАКРЫТ
#	Задача	Слож.	Время	Статус
0.1	Единый config_manager.py — FileLock, mkstemp, os.replace	🔴	2–3 ч	✅
0.2	Объект Config в памяти + подписки	🔴	2–3 ч	✅
0.3	Калибровка + адаптивный Barge-in	🔴	3–4 ч	✅
0.4	_prepare_text + CJK-фильтр	🟡	1–2 ч	✅
0.5	Few-shot промпт + temperature 0.7	🟡	1 ч	✅
0.6	Первые тесты (pytest + test_intents.py)	🟡	2–3 ч	✅
🔴 БАГФИКС-СЕССИИ (сначала стабилизация, потом фичи)
День 1 — срочный багфикс (ломает функционал) — ✅ ЗАКРЫТ
#	Задача	Слож.	Статус
1	actions.run_spec — обработка kind == "cmd" (Discord открывается)	🟢	✅
2	actions.find_process / _find_window — matching.match_score	🟡	✅
3	brain.py — close_app в отдельный блок промпта + главное правило	🟡	✅
4	intents._handle_single — вызов memory.handle_memory_command	🟢	✅
5	Удалить вкладка из гита	🟢	✅
6	tts.Speaker.stop() — рабочий barge-in через sounddevice	🔴	✅
7	stt._enable_cuda_dlls — флаг _CUDA_DLLS_ADDED	🟢	✅
8	snapshot.py — BASE.name вместо "jarvis/"	🟢	✅
9	tests/test_weather.py — убрать дубликаты	🟢	✅
11	intents._reload_packs — без config_copy	🟢	✅
Итог: barge-in реально прерывает звук (проверено голосом), Discord открывается/закрывается, память вызывается, тесты зелёные.

День 2 — добить багфикс — ❌ В РАБОТЕ
#	Задача	Слож.	Время	Статус
10	matching.match_score — ложные срабатывания на коротких словах («лок» → «блокнот»)	🔴	20 мин	❌
12	profile.set при битом user_profile.json — не терять данные молча	🟡	10 мин	❌
13	main.py — порядок импортов faster_whisper → ctranslate2 → winrt	🟢	5 мин	❌
14	install.bat — вынести python -c "..." в scripts/set_llm_model.py	🟢	15 мин	❌
15	requirements.txt — дополнить (pyautogui, pygetwindow, keyboard, mouse, pyperclip, psutil, pycaw, screen-brightness-control, pyinstaller)	🟢	5 мин	❌
День 3 — тесты и CI — ❌ НЕ НАЧАТ
#	Задача	Слож.	Время	Статус
16	test_intents.py — флаг --no-llm, дефолт --no-voice	🟡	20 мин	❌
17	test_intents.py — убрать hasattr(reply, "__iter__"), ввести Reply (namedtuple)	🟡	30 мин	❌
18	GitHub Actions — workflow на windows-latest: check_syntax + pytest + test_intents --no-llm	🟡	30 мин	❌
19	tests/test_weather.py — тесты на geocode и _get_weather_uncached с моком _http_get_json	🟡	20 мин	❌
День 4 — память и профиль — ❌ НЕ НАЧАТ
#	Задача	Слож.	Время	Статус
20	memory.save — батчить запись (раз в N сек или по событию)	🟡	30 мин	❌
21	memory.load + IntentHandler.dialog — грузить только последние 40 в deque, полные 200 — для describe	🟢	15 мин	❌
22	memory.handle_memory_command — вызывать до буфера и режимов (сделано в Дне 1)	🟢	—	✅
23	profile — расширить API: profile.get("name") → «Привет, {name}» в _small_talk	🟡	20 мин	❌
24	.gitignore — проверить, что user_profile.json, dialog.json, timers.json, tasks.json, config.json, logs/, models/ там	🟢	5 мин	❌
🟡 ЭТАП 2 — Незакрытые фичи
#	Задача	Слож.	Время	Статус
2.2	Погода и курс валют (open-meteo, cbr-xml-daily.ru, кэш 10 мин)	🟢	30 мин	✅
2.3	Буфер обмена (чтение, очистка, «скопируй выделенное», «скопируй свой ответ»)	🟢	20 мин	✅
2.4	Громкость/яркость в процентах (pycaw, screen-brightness-control)	🟢	30 мин	❌
2.8	Контекстные местоимения («скопируй это» через _context)	🟡	40 мин	❌
2.9	Цепочки с условиями (if/else)	🟡	1 ч	❌
2.10	Диктовка в файл	🟡	40 мин	❌
2.11	Поиск по файлам (рекурсивный os.walk)	🟡	45 мин	❌
2.12	Переключение раскладки RU/EN	🟢	15 мин	❌
2.13	Пароль на опасные команды	🟡	30 мин	❌
2.16	Стек отмены («отмени последнее», «верни голос», «отмени режим»)	🔴	1.5 ч	❌
2.26–2.30	Самообучение + persistent memory (learning.py, memory graph)	🔴	4 ч	❌
Примечание: 2.16 делается после 2.4–2.13. 2.26–2.30 — после 2.16.

🟠 ЭТАП 3 — Плагины и расширения
#	Задача	Слож.	Время	Статус
3.0	MCP-совместимость	🔴	3+ ч	❌
3.1	Система плагинов (папка plugins/)	🔴	2–3 ч	❌
3.2	Telegram-бот (после 3.1)	🔴	2–3 ч	❌
3.3	Веб-интерфейс (Flask, после 3.1)	🔴	2–3 ч	❌
🟢 ЭТАП 4 — Визуализация
#	Задача	Слож.	Время	Статус
4.1	Оверлей-индикатор (когда слушает)	🟡	1–1.5 ч	❌
4.2	Графический редактор команд	🔴	3–4 ч	❌
4.3	Аватар	🔴	3+ ч	❌
4.4	Лаунчер в трее	🟡	1–1.5 ч	❌
💤 ЭТАП 5 — Долгий ящик
#	Задача	Время
5.1	A2A-мост с Hermes Agent	5+ ч
5.2	Каталог голосов XTTS (Джарвис, Пятница, GLaDOS)	—
5.3	Smart Home (MQTT)	—
5.4	Календарь (Google Calendar, Windows Calendar)	—
5.5	Git-команды	—
5.6	Скриптовые плагины	—
