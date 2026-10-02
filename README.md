cd C:\jarvis
@'
# Феникс

Локальный голосовой ассистент для Windows. Форк проекта [jsays12/jarvis](https://github.com/jsays12/jarvis).

Полностью офлайн. Vosk ловит wake-слово, Whisper расшифровывает команду, Piper озвучивает ответ. Опционально — Qwen 2.5 через Ollama для свободного диалога и разбора сложных фраз.

## Что добавлено в форке

- LLM-фолбэк через Ollama: Qwen 2.5 (1.5B или 7B). Для 7B нужно 12+ ГБ VRAM.
- Печать текста в активное окно: «напечатай привет мир» (через pyautogui).
- Управление окнами: «сверни все окна», «сверни дискорд», «разверни браузер» (через pygetwindow).
- Открытие своего конфига голосом: «открой конфиг» → config.json в блокноте.
- Команды в терминале: через .bat-файлы в папке cmds/ (show_ip.bat, open_terminal.bat).
- Расширенный small talk: на «как дела» 7 разных ответов.
- Разговорчивый промпт: не отказывается от безобидных просьб (шутки, истории, объяснения).
- Правильная логика поиска: search только для свежих данных (погода, курс, новости) или явных просьб («найди», «загугли»). Остальное — answer.

## Требования

- Windows 10/11 (x64)
- Python 3.10+
- Микрофон
- Опционально: NVIDIA GPU (для Whisper large-v3-turbo и XTTS-v2)
- Опционально: Ollama (для LLM-фолбэка)

## Установка

1. Клонировать:

    git clone https://github.com/ТВОЙ_НИК/jarvis-fenix.git
    cd jarvis-fenix

2. Установить зависимости:

    pip install -r requirements.txt
    pip install pyautogui pygetwindow

3. Установить eSpeak NG (для Piper TTS). Без него TTS падает с ошибкой phonetab.

   Скачай espeak-ng-X.X.X-x64.msi с https://github.com/espeak-ng/espeak-ng/releases
   и установи со стандартными настройками. Потом закрой и открой cmd заново.

4. Установить Ollama (опционально):

    winget install Ollama.Ollama
    ollama pull qwen2.5:1.5b-instruct

   Для 12+ ГБ VRAM лучше: ollama pull qwen2.5:7b-instruct

5. Скопировать конфиг:

    copy config.example.json config.json

   И поправить под себя.

## Первый запуск

    python -m jarvis

При первом запуске скачается Vosk (~45 МБ) и Whisper (large-v3-turbo на GPU). Феникс произнесёт «Феникс запущен и готов к работе», и появится иконка в трее.

Если консоль вернула приглашение C:\jarvis> — процесс упал. Смотри лог.

## LLM (Ollama)

В config.json:

    "llm_model": "qwen2.5:7b-instruct",
    "use_llm": true,
    "ollama_url": "http://127.0.0.1:11434"

Проверка: ollama run qwen2.5:1.5b-instruct «расскажи шутку»

Модели:
- qwen2.5:1.5b-instruct — ~1.5 ГБ VRAM, базовое качество
- qwen2.5:3b-instruct — ~3 ГБ VRAM, лучше
- qwen2.5:7b-instruct — ~5-6 ГБ VRAM, отличное
- qwen2.5:14b-instruct — ~10 ГБ VRAM, максимум для 12 ГБ

## Команды

Приложения: «открой стим», «закрой дискорд», «запусти сабнатику».

Сайты: «открой ютуб», «открой сайт хабр», «хабр точка ру».

Поиск: «загугли погоду», «найди на ютубе лофи», «найди статью в википедии».

Печать: «напечатай привет мир» — курсор должен быть в нужном окне.

Окна: «сверни все окна», «сверни дискорд», «разверни браузер».

Скриншот: «сделай скриншот».

Файлы: «создай файл список покупок», «создай папку проекты», «что на рабочем столе».

Музыка: «включи музыку», «пауза», «следующий трек», «громче», «тише».

Время: «который час», «какое сегодня число».

Разговор: «как дела», «расскажи шутку», «что такое фотосинтез».

Своё: «открой конфиг», «покажи ip», «открой терминал».

## Свои команды в custom_commands

В config.json:

    {
      "phrases": ["открой конфиг"],
      "action": "C:\\jarvis\\config.json",
      "reply": "Открываю конфиг."
    }

Типы действий:
- Путь к файлу: C:\\jarvis\\config.json
- Путь к .bat: C:\\jarvis\\cmds\\show_ip.bat
- URL: https://example.com
- Steam-URI: steam://rungameid/570
- Цепочка шагов: steps: [{action, target}, ...]

## Голос

По умолчанию — Piper (ruslan). Смена в config.json:

    "tts_voice": "dmitri",
    "voice_rate": 1.0

Доступные голоса: ruslan, dmitri, irina, denis.

Прослушать: python scripts/voicedemo.py

Клонирование голоса (XTTS-v2): положи voices/jarvis.wav (10-30 секунд чистой речи) — при наличии NVIDIA GPU заговорит этим голосом. Медленнее Piper (2-5 сек на фразу), но голос как в фильме.

## Печать и окна

Печать: скажи «Феникс, напечатай привет мир». Перед командой поставь курсор в нужное окно. Работает через pyautogui.typewrite().

Окна:
- «сверни все окна» → Win+D
- «сверни дискорд» → ищет окно с «дискорд» в заголовке
- «разверни браузер» → разворачивает окно

Работает через pygetwindow. Имя ищется по подстроке, регистронезависимо.

## Запуск без консоли

    pythonw -m jarvis

Либо собрать .exe:

    python scripts/build_exe.py

Создаст Феникс.exe в корне проекта (~7 МБ).

## Автозапуск

Win+R → shell:startup → Enter. Скопируй туда ярлык на Феникс.exe или на pythonw -m jarvis.

## Траблшутинг

Консоль вернула приглашение после запуска — процесс упал, смотри лог.

Failed to create a model (Vosk) — модель не загрузилась. Проверь models/vosk-model-small-ru-0.22/am/final.mdl.

Error processing file ... phonetab (Piper) — не установлен eSpeak NG.

HTTP Error 404 про LLM — Ollama не запущена или модель не скачана. Проверь ollama list.

IndentationError после правки — сломал отступы. Используй Notepad++ с отображением пробелов.

Wake-слово не срабатывает — говори «ФЕ-НИКС» чётко, по слогам. Или попробуй «джарвис».

Постоянно ищет в поиске — проверь промпт SYSTEM в brain.py, там должно быть «search — только для свежих данных».

Отказывается от безобидных просьб — маленькая модель. Перейди на qwen2.5:7b-instruct.

## Технологии

- Wake-слово: Vosk (vosk-model-small-ru-0.22)
- Расшифровка: faster-whisper (large-v3-turbo на GPU, small на CPU)
- Синтез речи: Piper TTS (ruslan/dmitri), фолбэк — SAPI
- LLM: Qwen 2.5 через Ollama
- Микрофон: sounddevice (PortAudio)
- Трей: pystray + Pillow
- Печать/окна: pyautogui + pygetwindow

## Лицензия

См. оригинальный репозиторий jsays12/jarvis.
'@ | Out-File -FilePath README.md -Encoding utf8