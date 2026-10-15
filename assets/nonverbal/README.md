# Звуковые реакции: источники и использование

В проекте поставляются короткие производные CC0-записи для Non-verbal v1.
Проверка страниц источников и подготовка: 15.10.2026. Лицензия каждой записи —
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/).
CC0-записи могут распространяться и изменяться, включая коммерческое использование.
Авторство указано добровольно; права на исходный код проекта определяет корневой LICENSE.

| Файл | Автор | Источник | Фрагмент оригинала, с |
|---|---|---|---|
| `laugh.wav` | cchenail | [Freesound](https://freesound.org/people/cchenail/sounds/611480/) | 2.20–3.15 |
| `sigh.wav` | ValentinPetiteau | [Freesound](https://freesound.org/people/ValentinPetiteau/sounds/569568/) | 1.84–2.84 |
| `hmm.wav` | esperar | [Freesound](https://freesound.org/people/esperar/sounds/170777/) | 1.20–1.82 |
| `yawn.wav` | OwlStorm | [Freesound](https://freesound.org/people/OwlStorm/sounds/151240/) | 0.25–1.95 |

Точные URL скачанных HQ-preview, преобразования и SHA-256 лежат в `sources.json`.
Это производные фрагменты публичных HQ-preview, не заявленные как оригинальные lossless WAV.
Подготовка: обрезка, mono 22050 Hz PCM16, пик около −1.94 dBFS, fade-in/out 15 мс.
Рабочий микшер повторно подстраивает частоту и RMS-уровень под речь.

## Ограничения

- Записи фиксированные: голос/тембр не синтезируется под выбранный TTS и может отличаться.
- Четыре реакции: laugh, sigh, hmm, yawn. Кашля в поставке нет, он отложен.
- По умолчанию всё выключено; включение — вкладка «Аудио». SAPI без микширования.
- Автоматический выбор — по mood с учётом существующей prosody-политики, не новая ML-модель.
- Не заменять WAV на файл с неизвестными правами. Для нового сэмпла сохранять автора,
  страницу с проверенной CC0-лицензией, точный URL/преобразования и обновлённый хеш.
- `test_nonverbal.py` проверяет наличие, формат, длительность и хеши ресурсов.

## Прослушивание

Из корня проекта:

```powershell
.\.venv311\Scripts\python.exe tests/manual/nonverbal_live.py --kind hmm
.\.venv311\Scripts\python.exe tests/manual/nonverbal_live.py --kind laugh --mix speech.wav
```

Живой аудиопрогон и проверка тембра обязательны перед выпуском.
