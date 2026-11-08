# Документация Феникса

Короткая карта: что открыть, если нужен ответ прямо сейчас.

## С чего начать

| Документ | Когда открывать |
| --- | --- |
| [README](../README.md) | первое впечатление, быстрый старт, скриншоты |
| [Руководство пользователя](USER_GUIDE.md) | установка, команды, интерфейс, голос, диагностика |
| [Участие в разработке](../CONTRIBUTING.md) | стиль кода, тесты, требования к изменениям |
| [Тесты и CI](../CI.md) | что запускается на push и как читать красный CI |

## Установка и сборка

| Документ | О чём |
| --- | --- |
| [INSTALLER_UPDATE](INSTALLER_UPDATE.md) | что изменилось в установщике |
| [BOOTSTRAP_PYTHON_OLLAMA_UPDATE](BOOTSTRAP_PYTHON_OLLAMA_UPDATE.md) | мастер подготовки: Python, Ollama, модели |
| [BOOTSTRAP_WINDOW_UPDATE](BOOTSTRAP_WINDOW_UPDATE.md) | окно подготовки и его состояния |
| [PYTHON_BOOTSTRAP_TLS_FIX](PYTHON_BOOTSTRAP_TLS_FIX.md) | починка загрузки Python и TLS |
| [NUITKA_BUILD](NUITKA_BUILD.md) · [FULL_NUITKA_BUILD](FULL_NUITKA_BUILD.md) | автономная сборка Nuitka |
| [WINDOWS_STARTUP_RELIABILITY](WINDOWS_STARTUP_RELIABILITY.md) | надёжность запуска на Windows |
| [ACCEPTANCE_CHECKLIST](ACCEPTANCE_CHECKLIST.md) | чек-лист приёмки сборки |

## Интерфейс

| Документ | О чём |
| --- | --- |
| [GUI_HOME_UPDATE](GUI_HOME_UPDATE.md) | Главная: приветствие, статус, подсказки |
| [GUI_HOME_ACTION_RING](GUI_HOME_ACTION_RING.md) | действия вокруг птицы |
| [GUI_WIDGETS_UPDATE](GUI_WIDGETS_UPDATE.md) | виджеты Главной |
| [GUI_PERSONA_SETTINGS_UPDATE](GUI_PERSONA_SETTINGS_UPDATE.md) | Персона и настройки |
| [GUI_SIDEBAR_UPDATE](GUI_SIDEBAR_UPDATE.md) · [GUI_SIDEBAR_PUSH_FIX](GUI_SIDEBAR_PUSH_FIX.md) | боковая панель |
| [GUI_SOLAR_AURA_UPDATE](GUI_SOLAR_AURA_UPDATE.md) · [GUI_SOLAR_AURA_SMOOTH_UPDATE](GUI_SOLAR_AURA_SMOOTH_UPDATE.md) · [GUI_SOLAR_AURA_ALWAYS_UPDATE](GUI_SOLAR_AURA_ALWAYS_UPDATE.md) | аура птицы |
| [GUI_STARTUP_TRAY_FIX](GUI_STARTUP_TRAY_FIX.md) | запуск и трей |

## Голос, звук и речь

| Документ | О чём |
| --- | --- |
| [LOCAL_VOICE_OPTIONS](LOCAL_VOICE_OPTIONS.md) | Silero, Piper, SAPI — чем озвучивать |
| [AEC_PIPER_PROTOTYPE](AEC_PIPER_PROTOTYPE.md) · [AEC_SAMPLE_ALIGNMENT_UPDATE](AEC_SAMPLE_ALIGNMENT_UPDATE.md) | эхоподавление и выравнивание сэмплов |
| [AEC_LOCAL_DIAGNOSTICS](AEC_LOCAL_DIAGNOSTICS.md) | локальная диагностика AEC |
| [TTS_LIFECYCLE_FIX](TTS_LIFECYCLE_FIX.md) | жизненный цикл озвучки |
| [WHISPER_STARTUP_DLL_FIX](WHISPER_STARTUP_DLL_FIX.md) | старт faster-whisper и DLL |
| [WINRT_TTS_REMOVAL](WINRT_TTS_REMOVAL.md) | почему убран WinRT TTS |

## Модели и сеть

| Документ | О чём |
| --- | --- |
| [CLOUD_LLM](CLOUD_LLM.md) | внешняя LLM в настройках и её границы |
| [PHOENIX_JASTIN_RECONCILIATION](PHOENIX_JASTIN_RECONCILIATION.md) | цель JASTIN и текущее состояние |

## Планы, история и проверки

| Документ | О чём |
| --- | --- |
| [NEXT_STEPS](NEXT_STEPS.md) | очередь работ |
| [IMPROVEMENT_BACKLOG](IMPROVEMENT_BACKLOG.md) | бэклог улучшений |
| [REVIEW_FIXES](REVIEW_FIXES.md) | разборы замечаний |
| [HANDOFF_VALIDATION](HANDOFF_VALIDATION.md) | текущий отчёт проверок |
| [releases/](releases/) | заметки к версиям |

> В корне: [README](../README.md) — витрина, [CHANGELOG](../CHANGELOG.md) — что менялось,
> [ARCHITECTURE](../ARCHITECTURE.md) — как устроено, [PLAN](../PLAN.md) — куда движемся.
