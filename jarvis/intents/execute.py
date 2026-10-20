"""Dispatch: action → функция-обработчик.

Здесь вся логика выполнения интентов:
    - open_app / close_app / open_site / search
    - screenshot / open_folder / list_folder / create_file
    - media_key / play_pause / next_track / prev_track
    - volume_* / brightness_* / layout_*
    - clipboard_*
    - minimize_* / maximize_* / activate_* / switch_*
    - set_mode / load_pack / unload_pack / list_packs
    - change_voice / list_voices
    - set_timer / list_timers / cancel_timers
    - add_task / list_tasks / done_task / remove_task / clear_tasks
    - open_config / open_log / open_profile
    - get_weather / get_currency
    - set_profile / get_profile / delete_profile
    - answer

`execute_steps` — многошаговые сценарии.

Побочное: history.push(...) для отмены.
"""

import datetime
import logging
import re
import time

from jarvis import actions, files, history, uia
from jarvis import modes, packs, profile, tasks, timers, voices, weather
from jarvis import paths as _paths
from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.intents")
actions_log = logging.getLogger("jarvis.actions")


# =================================================================
# Weather / currency — sanity-проверка на мусорный target
# =================================================================

_WEATHER_BAD_TARGET = (
    "курс", "доллар", "рубл", "евро", "юан", "валют",
    "цену", "цена", "поиск", "найди", "погод", "прогноз",
    "пожалуйста", "сколько", "стоит",
)

_FOLDER_TITLES = {
    "Desktop": "на рабочем столе", "Downloads": "в загрузках",
    "Documents": "в документах", "Pictures": "в изображениях",
    "Music": "в музыке", "Videos": "в видео",
    "Screenshots": "в скриншотах",
}


# =================================================================
# Точка входа
# =================================================================

def execute_intent(handler, intent: dict) -> str | None:
    """Находит обработчик в _DISPATCH и вызывает."""
    action = intent.get("action")
    target = normalize(str(intent.get("target") or ""))
    query = str(intent.get("query") or "").strip()

    actions_log.info("Интент: %s (target=%r, query=%r)", action, target, query)

    fn = _DISPATCH.get(action)
    if fn is None:
        return None
    try:
        return fn(handler, intent, target, query)
    except OSError:
        actions_log.exception("Ошибка выполнения действия %s", action)
        return "Не удалось выполнить действие: ошибка доступа или записи данных."


def execute_steps(handler, steps: list) -> str | None:
    """Многошаговый сценарий.

    ВАЖНО: push_macro делаем ТОЛЬКО для успешно выполненных шагов.
    """
    reply = None
    executed: list = []

    for step in steps[:6]:
        if not isinstance(step, dict):
            continue
        action = step.get("action")
        if action == "wait":
            time.sleep(min(float(step.get("seconds", 1) or 1), 15))
            executed.append(step)
            continue
        if action == "media_key":
            actions.media_key(str(step.get("key", "")), int(step.get("times", 1) or 1))
            executed.append(step)
            continue
        r = execute_intent(handler, step)
        if r:
            reply = r
        executed.append(step)

    real_steps = [s for s in executed
                  if isinstance(s, dict) and s.get("action") not in ("wait",)]
    if real_steps:
        history.push_macro(real_steps)

    return reply


# =================================================================
# Обработчики
# =================================================================

def _do_open_app(handler, intent, target, query):
    from jarvis.apps import find_app
    from jarvis.installed import find_installed

    if not target:
        return None
    if intent.get("minimized"):
        hit = find_installed(handler.installed, target)
        if hit:
            actions.open_path(hit[1], minimized=True)
            return f"Открываю {hit[0]}."
    running = actions.find_process(target, threshold=0.8)
    if running:
        from jarvis.actions import activate_window_by_title
        if activate_window_by_title(target):
            return f"Переключаюсь на {target}."
    return _do_open(handler, target)


def _do_close_app(handler, intent, target, query):
    if not target:
        return None
    return _do_close(handler, target)


def _do_open_file(handler, intent, target, query):
    if handler.last_file:
        actions.open_path(handler.last_file)
        return "Открываю."
    return "Пока нечего открывать."


def _do_open_site(handler, intent, target, query):
    # Берём СЫРОЙ target из intent, а не нормализованный: normalize()
    # вырезает пунктуацию, и «habr.com» превращается в «habr com».
    # Раньше из-за этого ответ озвучивался как «Открываю habr com»,
    # а неизвестные домены уходили в guess_site и открывались
    # как gismeteoru.ru.
    raw = str(intent.get("target") or "").strip()
    site = raw or query
    if not site:
        return None
    if "." in raw:
        url = actions.normalize_url(raw)
        actions.open_url(url)
        return f"Открываю {site}."
    return _open_site(site)


def _do_search(handler, intent, target, query):
    q = query or target
    if not q:
        return None
    engine = intent.get("engine")
    if engine not in ("google", "youtube", "wiki"):
        engine = "google"
    actions.open_search(engine, q)
    return f"Ищу: {q}."


def _do_screenshot(handler, intent, target, query):
    path = actions.take_screenshot()
    handler.last_file = path
    return f"Скриншот сохранён в папку {path.parent.name}."


def _do_open_folder(handler, intent, target, query):
    if not target:
        return None
    # explicit только со словом «папка» — как в _do_open. Иначе
    # «открой музыку» открывала папку Music вместо плеера, хотя
    # комментарий в files.py прямо требует обратного.
    folder = files.resolve_folder(target, explicit="папк" in target)
    if folder:
        handler.last_folder = folder
        files.open_folder(folder)
        return f"Открываю папку {folder.name}."
    return None


def _do_list_folder(handler, intent, target, query):
    folder = (files.resolve_folder(target, explicit="папк" in target)
              if target else handler.last_folder)
    if folder:
        handler.last_folder = folder
        return files.describe_folder(folder)
    return None


def _do_create_file(handler, intent, target, query):
    folder_name = str(intent.get("folder") or "").strip()
    folder = None
    if folder_name:
        folder = files.resolve_folder(folder_name, explicit=True)
        if folder is None:
            return f"Папку «{folder_name}» не нашёл. Куда создать файл?"
    if folder is None:
        folder = _paths.user_home() / "Desktop"
    path = files.create_file(folder, target or "новый файл")
    handler.last_file = path
    title = _FOLDER_TITLES.get(folder.name, f"в папке {folder.name}")
    return f"Создал {path.name} {title}."


def _do_type_text(handler, intent, target, query):
    text = str(intent.get("text") or intent.get("target") or "").strip()
    ok = actions.type_text(text)
    return f"Печатаю: {text}." if ok else "Не удалось напечатать."


# ------------------------------------------------------------------
# Горячие клавиши: «нажми контрл эс» → hotkey(["ctrl", "s"])
# ------------------------------------------------------------------

_SPOKEN_KEYS = {
    "контрл": "ctrl", "контроль": "ctrl", "ctrl": "ctrl", "control": "ctrl",
    "шифт": "shift", "сдвиг": "shift", "shift": "shift",
    "альт": "alt", "алт": "alt", "alt": "alt",
    "вин": "win", "виндовс": "win", "win": "win",
    "энтер": "enter", "интер": "enter", "ввод": "enter", "enter": "enter",
    "таб": "tab", "табуляция": "tab", "tab": "tab",
    "эскейп": "esc", "escape": "esc", "esc": "esc",
    "пробел": "space", "space": "space",
    "бэкспейс": "backspace", "стереть": "backspace", "backspace": "backspace",
    "делит": "delete", "удалить": "delete", "delete": "delete",
    "вверх": "up", "вниз": "down", "влево": "left", "вправо": "right",
    "хип": "home", "энд": "end", "home": "home", "end": "end",
}

# Латинские буквы, которые Vosk произносит русскими словами: «эс» → s.
_LETTER_KEYS = {
    "эй": "a", "би": "b", "си": "c", "ди": "d", "эф": "f",
    "джи": "g", "эйч": "h", "ай": "i", "джей": "j", "кей": "k", "эл": "l",
    "эм": "m", "эн": "n", "пи": "p", "кью": "q", "эр": "r",
    "эс": "s", "ти": "t", "икс": "x", "уай": "y", "зед": "z", "зет": "z",
}


def _parse_hotkey(text: str) -> list[str]:
    """«контрл эс» / «ctrl+s» / «alt tab» → ["ctrl", "s"].

    Непонятные куски пропускаем: нажать меньше клавиш безопаснее, чем
    наугад ткнуть в чужую комбинацию. Ожидаются однословные токены —
    так их и пишет Vosk («дабл ю» не поддержан, кириллица как клавиша —
    только через `_LETTER_KEYS`).
    """
    keys = []
    for part in re.split(r"[\s+,]+", (text or "").lower()):
        if not part:
            continue
        if part in _SPOKEN_KEYS:
            keys.append(_SPOKEN_KEYS[part])
        elif part in _LETTER_KEYS:
            keys.append(_LETTER_KEYS[part])
        elif len(part) <= 3 and part.isascii() and part.isalnum():
            keys.append(part)          # «s», «f5», «1»
    return keys


def _do_hotkey(handler, intent, target, query):
    raw = intent.get("keys")
    if isinstance(raw, list):
        keys = [str(k).strip().lower() for k in raw if str(k).strip()]
    elif isinstance(raw, str):
        keys = _parse_hotkey(raw)
    else:
        keys = []

    if not keys:
        keys = _parse_hotkey(target or query)
    if not keys:
        return "Не понял, какие клавиши нажать."
    if not actions.hotkey(keys):
        return "Не удалось нажать клавиши."
    return f"Нажимаю {', '.join(keys)}."


def _do_media_key(handler, intent, target, query):
    ok = actions.media_key(str(intent.get("key", "")),
                           int(intent.get("times", 1) or 1))
    return "Готово." if ok else None


def _do_play_pause(handler, intent, target, query):
    actions.media_key("play")
    return "Готово."


def _do_next_track(handler, intent, target, query):
    actions.media_key("next")
    return "Переключаю."


def _do_prev_track(handler, intent, target, query):
    actions.media_key("prev")
    return "Возвращаю."


def _do_volume_up(handler, intent, target, query):
    actions.media_key("vol_up", 5)
    return "Громче."


def _do_volume_down(handler, intent, target, query):
    actions.media_key("vol_down", 5)
    return "Тише."


def _do_mute(handler, intent, target, query):
    actions.media_key("mute")
    return "Без звука."


def _do_switch_layout(handler, intent, target, query):
    ok = actions.switch_layout()
    if ok:
        history.push({"action": "switch_layout"})
    return "Переключаю раскладку." if ok else None


def _do_set_layout_ru(handler, intent, target, query):
    return "Русская раскладка." if actions.set_layout_ru() else None


def _do_set_layout_en(handler, intent, target, query):
    return "Английская раскладка." if actions.set_layout_en() else None


def _do_get_layout(handler, intent, target, query):
    layout = actions.get_layout()
    if layout == "ru":
        return "Русская раскладка."
    if layout == "en":
        return "Английская раскладка."
    return None


def _do_set_volume(handler, intent, target, query):
    try:
        pct = int(intent.get("percent", 50))
    except (TypeError, ValueError):
        pct = 50
    prev = actions.get_volume()
    ok = actions.set_volume(pct)
    if ok:
        history.push({"action": "set_volume", "prev_value": prev})
    return f"Громкость: {pct}%." if ok else None


def _do_get_volume(handler, intent, target, query):
    vol = actions.get_volume()
    return f"Громкость: {vol}%." if vol is not None else None


def _do_set_brightness(handler, intent, target, query):
    try:
        pct = int(intent.get("percent", 50))
    except (TypeError, ValueError):
        pct = 50
    prev = actions.get_brightness()
    ok = actions.set_brightness(pct)
    if ok:
        history.push({"action": "set_brightness", "prev_value": prev})
    return f"Яркость: {pct}%." if ok else None


def _do_get_brightness(handler, intent, target, query):
    br = actions.get_brightness()
    return f"Яркость: {br}%." if br is not None else None


def _do_clipboard_read(handler, intent, target, query):
    text = actions.clipboard_read()
    if not text:
        return "Буфер обмена пуст."
    return f"В буфере: {text[:400]}"


def _do_copy_selection(handler, intent, target, query):
    if not actions.copy_selection():
        return "Не удалось скопировать."
    time.sleep(0.15)
    text = actions.clipboard_read()
    if text:
        short = text[:200] + ("..." if len(text) > 200 else "")
        return f"Скопировал: {short}"
    return "Скопировал выделенное."


def _do_clipboard_copy_last(handler, intent, target, query):
    last = handler._last_reply
    if not last:
        return "Нечего копировать."
    ok = actions.clipboard_write(last)
    return "Скопировал свой ответ в буфер." if ok else "Не удалось скопировать."


def _do_clipboard_clear(handler, intent, target, query):
    ok = actions.clipboard_clear()
    return "Буфер очищен." if ok else "Не удалось очистить буфер."


def _do_minimize_all(handler, intent, target, query):
    actions.minimize_all()
    return "Сворачиваю всё."


def _do_minimize_window(handler, intent, target, query):
    if not target:
        return None
    ok = actions.minimize_window_by_title(target)
    return f"Сворачиваю {target}." if ok else f"Окно {target} не нашёл."


def _do_maximize_window(handler, intent, target, query):
    if not target:
        return None
    ok = actions.maximize_window_by_title(target)
    return f"Разворачиваю {target}." if ok else f"Окно {target} не нашёл."


def _do_activate_window(handler, intent, target, query):
    if not target:
        return None
    ok = actions.activate_window_by_title(target)
    return f"Переключаюсь на {target}." if ok else f"Окно {target} не нашёл."


def _do_minimize_active(handler, intent, target, query):
    actions.minimize_active()
    return "Сворачиваю активное окно."


def _do_maximize_active(handler, intent, target, query):
    actions.maximize_active()
    return "Разворачиваю активное окно."


def _do_switch_window(handler, intent, target, query):
    actions.switch_window(back=bool(intent.get("back")))
    return "Переключаю окно."


def _do_set_mode(handler, intent, target, query):
    prev_mode = handler.mode
    mode = str(intent.get("mode") or "combo").lower()
    if mode not in ("commands", "llm", "combo"):
        mode = "combo"
    reply = modes.set_mode(mode, handler.config)
    if mode != prev_mode:
        history.push({"action": "set_mode", "prev_value": prev_mode})
    handler.mode = mode
    return reply


def _do_load_pack(handler, intent, target, query):
    name = packs.normalize_name(str(intent.get("name") or ""))
    available = packs.list_available()
    if name not in available:
        return f"Пак '{name}' не найден. Доступны: {', '.join(available)}."
    if name in handler.active_packs:
        return f"Пак '{name}' уже активен."
    handler.active_packs.append(name)
    packs.save_active(handler.active_packs, handler.config)
    _reload_packs(handler)
    return f"Пак '{name}' загружен."


def _do_unload_pack(handler, intent, target, query):
    name = packs.normalize_name(str(intent.get("name") or ""))
    if name not in handler.active_packs:
        return f"Пак '{name}' и так не активен."
    handler.active_packs.remove(name)
    packs.save_active(handler.active_packs, handler.config)
    _reload_packs(handler)
    return f"Пак '{name}' выгружен."


def _do_list_packs(handler, intent, target, query):
    available = packs.list_available()
    active_str = ", ".join(handler.active_packs) if handler.active_packs else "нет"
    return f"Доступны: {', '.join(available)}. Активны: {active_str}."


def _do_change_voice(handler, intent, target, query):
    prev = voices.current_voice(handler.config)
    voice = str(intent.get("voice") or "").strip()
    if not voice:
        return ("Не расслышал, какой голос включить. "
                "Скажите, например: «смени голос на ирину».")

    reply = voices.switch(voice, handler.config)

    # В историю — только если голос реально сменился, иначе
    # «верни как было» откатит к тому же самому голосу.
    if voices.current_voice(handler.config) != prev:
        history.push({"action": "change_voice", "prev_value": prev})
    return reply


def _do_list_voices(handler, intent, target, query):
    return voices.handle_voice_command("список голосов", handler.config)


def _do_set_timer(handler, intent, target, query):
    text = str(intent.get("text") or "").strip()
    seconds = intent.get("seconds")
    time_str = intent.get("time")
    fire_at = None

    if seconds:
        try:
            fire_at = time.time() + float(seconds)
        except (TypeError, ValueError):
            fire_at = None
    elif time_str:
        try:
            hh, mm = str(time_str).split(":")
            now = datetime.datetime.now()
            t = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if t <= now:
                t += datetime.timedelta(days=1)
            fire_at = t.timestamp()
        except Exception:
            fire_at = None

    if fire_at:
        timers.add(text, fire_at)
        when = datetime.datetime.fromtimestamp(fire_at).strftime("%H:%M")
        return f"Напомню в {when}: {text}." if text else f"Напомню в {when}."
    return "Не понял время напоминания."


def _do_list_timers(handler, intent, target, query):
    return timers.format_list(timers.list_all())


def _do_cancel_timers(handler, intent, target, query):
    n = timers.remove_all()
    return f"Отменено напоминаний: {n}." if n else "Напоминаний не было."


def _do_add_task(handler, intent, target, query):
    text = str(intent.get("text") or intent.get("task") or "").strip()
    if not text:
        return "Что добавить?"
    task = tasks.add(text)
    return f"Добавил: {task['text']}."


def _do_list_tasks(handler, intent, target, query):
    return tasks.format_list()


def _do_done_task(handler, intent, target, query):
    q = str(intent.get("task") or "").strip()
    task = tasks.mark_done(q)
    return f"Отметил: {task['text']}." if task else f"Задачу «{q}» не нашёл."


def _do_remove_task(handler, intent, target, query):
    q = str(intent.get("task") or "").strip()
    task = tasks.remove(q)
    return f"Убрал: {task['text']}." if task else f"Задачу «{q}» не нашёл."


def _do_clear_tasks(handler, intent, target, query):
    n = tasks.clear_all()
    return f"Очищено задач: {n}." if n else "Список и так пуст."


def _do_open_config(handler, intent, target, query):
    actions.open_path(_paths.config_path())
    return "Открываю конфиг."


def _do_open_log(handler, intent, target, query):
    log_path = _paths.logs_dir() / "jarvis.log"
    actions.open_path(log_path)
    return "Открываю журнал."


def _do_open_profile(handler, intent, target, query):
    prof_path = profile.profile_path()
    prefer = str(intent.get("editor") or "auto").lower()
    ok = actions.open_in_editor(prof_path, prefer=prefer)
    if ok:
        return f"Открываю профиль {profile.current()}."
    return f"Не удалось открыть профиль: {prof_path}"


def _do_get_weather(handler, intent, target, query):
    city = str(intent.get("target") or "").strip()
    day = "tomorrow" if intent.get("day") == "tomorrow" else "today"

    if any(w in city.lower() for w in _WEATHER_BAD_TARGET):
        log.warning("get_weather: LLM подсунула мусор target=%r — игнорирую", city)
        city = ""

    if not city:
        city = profile.get("default_city")
    if not city:
        handler._pending_question = {
            "type": "city_for_weather",
            "day": day,
            "expires_at": time.time() + 30,
        }
        return "В каком городе узнать погоду?"

    w = weather.get_weather(city, day=day)
    if not w:
        return f"Не удалось узнать погоду для «{city}». Проверь название или интернет."
    return weather.describe_weather(w)


def _do_get_currency(handler, intent, target, query):
    code = str(intent.get("target") or "").strip().upper()
    r = weather.get_currency_rates()
    return weather.describe_currency(r, code=code)


def _do_delete_profile(handler, intent, target, query):
    name = str(intent.get("target") or "").strip()
    if profile.delete(name):
        return f"Профиль {name} удалён."
    return f"Профиль {name} не найден или активен."


_KEY_MAP = {
    "имя": "name", "name": "name",
    "город": "default_city", "default_city": "default_city",
    "city": "default_city", "мой город": "default_city",
}


def _do_set_profile(handler, intent, target, query):
    key = str(intent.get("key") or "").strip()
    value = str(intent.get("value") or "").strip()
    if not key or not value:
        return "Не понял, что сохранить."

    key = _KEY_MAP.get(key.lower(), key.lower())
    if key not in ("name", "default_city", "prev_city"):
        return f"Не знаю, что такое «{key}»."

    if key == "default_city":
        prev = profile.get("default_city")
        if prev and prev.lower() != value.lower():
            profile.set("prev_city", prev)

    if profile.set(key, value):
        if key == "name":
            return f"Имя изменено на {value}."
        if key == "default_city":
            return f"Город изменён на {value}."
        return f"Сохранено: {key} = {value}."
    return "Не удалось сохранить."


def _do_get_profile(handler, intent, target, query):
    key = str(intent.get("key") or "").strip()
    key = _KEY_MAP.get(key.lower(), key.lower())

    if key == "name":
        v = profile.get("name")
        return f"Тебя зовут {v}." if v else "Имя не задано."
    if key == "default_city":
        v = profile.get("default_city")
        return f"Твой город — {v}." if v else "Город не задан."
    return "Не знаю, что прочитать."


def _do_power(handler, intent, target, query):
    # Typed builder actions: only fixed argv, no arbitrary shell text.
    if not handler.config.get("danger_password"):
        return "Для выключения и перезагрузки нужен пароль опасных действий."
    action = intent.get("action")
    from jarvis.command_builder import validate_step
    seconds = validate_step(intent)["seconds"]
    flag = "/s" if action == "shutdown_pc" else "/r"
    ok = actions.run_power_action(flag, seconds)
    return (f"{'Выключение' if flag == '/s' else 'Перезагрузка'} через {seconds} секунд. "
            "Для отмены скажи «отмени выключение».") if ok else "Не удалось запланировать действие."


def _do_cancel_shutdown(handler, intent, target, query):
    return ("Выключение / перезагрузка отменены." if actions.run_power_action("/a")
            else "Не удалось отменить выключение / перезагрузку.")


def _do_answer(handler, intent, target, query):
    reply = intent.get("reply")
    return str(reply)[:600] if reply else None


# =================================================================
# Открытие / закрытие — вынесено сюда, используется в open_app
# =================================================================

BROWSER_WORDS = frozenset({
    "браузер", "браузере", "браузером",
    "хром", "хроме", "интернет", "интернете",
})

# Конкретные браузеры: «открой хром» — это именно Chrome, а не браузер
# по умолчанию (№1). «Яндекс» сюда не входит намеренно: «открой яндекс»
# чаще про сайт (yandex.ru), а не про Яндекс.Браузер.
_BROWSER_PROCS = {
    "хром": "chrome.exe",
    "chrome": "chrome.exe",
    "эдж": "msedge.exe",
    "едж": "msedge.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "фаерфокс": "firefox.exe",
    "файрфокс": "firefox.exe",
    "опера": "opera.exe",
    "opera": "opera.exe",
    "brave": "brave.exe",
    "вивальди": "vivaldi.exe",
    "vivaldi": "vivaldi.exe",
    "arc": "arc.exe",
}


# Слова-«наполнители» в «закрой все окна проводника»: без чистки find_app
# видит не «проводник», а «все окна проводника», и приложение не находит.
_MASS_WORDS = frozenset({
    "все", "всё", "всех", "окна", "окон", "окно", "окошка",
    "приложение", "приложения", "программу", "программы",
})


def _do_open(handler, target: str) -> str:
    """Открыть что угодно: приложение, сайт, папку, игру, ярлык."""
    from jarvis.apps import find_app
    from jarvis.installed import find_installed
    from jarvis.steam import find_game
    from jarvis.intents.sites import get_sites

    if not target:
        return "Что именно открыть?"
    if target in {"его", "ее", "это", "этот файл", "файл", "последний файл"}:
        if handler.last_file:
            actions.open_path(handler.last_file)
            return "Открываю."
        return "Пока нечего открывать."

    tokens = target.split()
    # «открой хром» — это Chrome, а не браузер по умолчанию (№1): если он
    # уже запущен, переключаемся на его окно, а не плодим новое.
    named = next((t for t in tokens if t in _BROWSER_PROCS), None)
    rest = [t for t in tokens if t not in BROWSER_WORDS and t != named]

    if named and not rest:
        process = _BROWSER_PROCS[named]
        if actions.focus_browser(process):
            return f"Переключаюсь на {named}."
        app = find_app(handler.apps, named)
        spec = app.resolve_open() if app else None
        if spec is not None:
            if not actions.run_spec(spec):
                return f"Не удалось открыть {named}. Windows не подтвердила запуск."
            return f"Открываю {named}."
        actions.open_browser(process)
        return f"Открываю {named}."

    if len(rest) < len(tokens):
        if not rest:
            actions.open_browser()
            return "Открываю браузер."
        return _open_site(" ".join(rest))

    app = find_app(handler.apps, target)
    if app:
        spec = app.resolve_open()
        if spec is None:
            return f"{app.title} не найден на этом компьютере."
        if not actions.run_spec(spec):
            return f"Не удалось открыть {app.title}. Проверь, установлено ли приложение."
        return f"Открываю {app.title}."

    for key, (title, url) in get_sites().items():
        if key in target.split() or target == key:
            actions.open_url(url)
            return f"Открываю {title}."

    folder = files.resolve_folder(target, explicit="папк" in target)
    if folder:
        handler.last_folder = folder
        files.open_folder(folder)
        return f"Открываю папку {folder.name}."

    game = find_game(handler.steam_games, target)
    if game:
        title, appid = game
        if not actions.run_spec(("uri", f"steam://rungameid/{appid}")):
            return "Не удалось передать запуск игры в Steam."
        return f"Запускаю {title}."

    hit = find_installed(handler.installed, target)
    if hit:
        name, lnk = hit
        actions.open_path(lnk)
        return f"Открываю {name}."

    return _open_site(target)


def _open_site(name: str) -> str:
    from jarvis.intents.sites import get_sites

    if not name:
        return "Какой сайт открыть?"
    for key, (title, url) in get_sites().items():
        if name == key or key in name.split():
            actions.open_url(url)
            return f"Открываю {title}."
    url = actions.spoken_domain(name) or actions.guess_site(name)
    if url:
        actions.open_url(url)
        return f"Открываю сайт {name}."
    return f"Сайт {name} не нашёл. Скажите «найди {name}», и я поищу."


def _do_close(handler, target: str) -> str:
    from jarvis.apps import find_app

    if not target:
        return "Что именно закрыть?"

    # «закрой все окна проводника»: без чистки наполнителей find_app видит
    # не «проводник», а «все окна проводника» и приложение не находит.
    words = [w for w in target.split() if w not in _MASS_WORDS]
    mass = len(words) < len(target.split())
    name = " ".join(words) or target

    if any(w in target for w in ("браузер", "интернет", "хром")):
        return "Закрываю браузер." if actions.close_browser() else "Браузер не запущен."

    app = find_app(handler.apps, name)
    title = app.title if app else None
    procs = list(app.procs) if app else []

    if not procs:
        # Вне каталога — только уверенное совпадение (0.9). На пороге 0.7
        # «закрой клод» убивал gcloud.exe (0.80), а «закрой диспетчер
        # задач» — pet.exe (0.90). Лучше сказать «не нашёл», чем закрыть
        # чужую программу.
        exe = actions.find_process(name, threshold=0.9)
        if exe:
            actions.kill_process(exe)
            return f"Закрываю {exe.removesuffix('.exe')}."
        if title:
            return f"{title} сейчас не запущен."
        return f"Не нашёл запущенной программы {name}."

    # Проводник и прочие защищённые процессы не убиваем — закрываем их ОКНА
    # (`close_windows_by_process`): завершение explorer.exe перезапускает
    # рабочий стол, и «закрой проводник» выглядело бы как поломка.
    if mass or any(actions.is_protected_process(p) for p in procs):
        closed = actions.close_windows_by_process(procs)
        if closed:
            return f"Закрыл окон: {closed}." if mass else f"Закрываю {title}."
        if title:
            return f"Открытых окон {title} не нашёл."
        return f"Открытых окон {name} не нашёл."

    if any(actions.kill_process(p) for p in procs):
        return f"Закрываю {title}."
    return f"{title} сейчас не запущен."


def _reload_packs(handler) -> None:
    from jarvis.intents.fast.custom import reload_custom
    reload_custom(handler)


# =================================================================
# UIA-обработчики
# =================================================================

def _do_uia_read_window(handler, intent, target, query):
    text = uia.read_active_text_stripped(max_chars=1500)
    if not text:
        return "В активном окне не вижу текста."
    if len(text) > 400:
        text = text[:400] + "... (ещё много)"
    return f"Читаю: {text}"


def _do_uia_read_url(handler, intent, target, query):
    url = uia.read_browser_url()
    if not url:
        return "Активное окно — не браузер, или не вижу URL."
    return f"Открыт сайт: {url}"


def _do_uia_read_tab(handler, intent, target, query):
    title = uia.read_browser_tab_title()
    if not title:
        return "Активное окно — не браузер."
    return f"Активная вкладка: {title}"


def _do_uia_list_tabs(handler, intent, target, query):
    tabs = uia.read_browser_tabs()
    if not tabs:
        return "Не вижу открытых вкладок."
    return "Открыты: " + "; ".join(tabs[:10]) + "."


def _do_uia_close_tab(handler, intent, target, query):
    if not target:
        return "Какую вкладку закрыть?"
    if target.lower() in ("эту", "текущую", "это"):
        actions.hotkey(["ctrl", "w"])
        return "Закрыл текущую вкладку."
    # `_with_fallback` — тот же запасной ход Ctrl+W, что и в fast-ветке:
    # браузер может не отдавать список вкладок (Яндекс группирует их).
    ok = uia.close_browser_tab_with_fallback(target)
    return f"Закрыл вкладку {target}." if ok else f"Вкладку «{target}» не нашёл."


def _do_uia_switch_tab(handler, intent, target, query):
    if not target:
        return "На какую вкладку переключиться?"
    if target.lower() in ("эту", "текущую", "это"):
        return "Эта вкладка уже открыта."
    ok = uia.switch_browser_tab_with_fallback(target)
    return f"Переключился на {target}." if ok else f"Вкладку «{target}» не нашёл."


def _do_uia_click_button(handler, intent, target, query):
    if not target:
        return "Какую кнопку нажать?"
    ok = uia.click_button(target)
    return f"Нажал «{target}»." if ok else f"Кнопку «{target}» не нашёл."


def _do_uia_active_window(handler, intent, target, query):
    return uia.describe_active_window()


def _do_uia_menu(handler, intent, target, query):
    if not target:
        return "Какой пункт меню?"
    ok = uia.click_menu_item(target)
    return f"Кликнул: {target}." if ok else f"Меню «{target}» не нашёл."


# =================================================================
# Dispatch-таблица
# =================================================================

_DISPATCH = {
    "shutdown_pc": _do_power,
    "reboot_pc": _do_power,
    "cancel_shutdown": _do_cancel_shutdown,
    "open_app":           _do_open_app,
    "close_app":          _do_close_app,
    "open_file":          _do_open_file,
    "open_site":          _do_open_site,
    "search":             _do_search,
    "screenshot":         _do_screenshot,
    "open_folder":        _do_open_folder,
    "list_folder":        _do_list_folder,
    "create_file":        _do_create_file,
    "type_text":          _do_type_text,
    "hotkey":             _do_hotkey,
    "media_key":          _do_media_key,
    "play_pause":         _do_play_pause,
    "next_track":         _do_next_track,
    "prev_track":         _do_prev_track,
    "volume_up":          _do_volume_up,
    "volume_down":        _do_volume_down,
    "mute":               _do_mute,
    "switch_layout":      _do_switch_layout,
    "set_layout_ru":      _do_set_layout_ru,
    "set_layout_en":      _do_set_layout_en,
    "get_layout":         _do_get_layout,
    "set_volume":         _do_set_volume,
    "get_volume":         _do_get_volume,
    "set_brightness":     _do_set_brightness,
    "get_brightness":     _do_get_brightness,
    "clipboard_read":     _do_clipboard_read,
    "copy_selection":     _do_copy_selection,
    "clipboard_copy_last": _do_clipboard_copy_last,
    "clipboard_clear":    _do_clipboard_clear,
    "minimize_all":       _do_minimize_all,
    "minimize_window":    _do_minimize_window,
    "maximize_window":    _do_maximize_window,
    "activate_window":    _do_activate_window,
    "minimize_active":    _do_minimize_active,
    "maximize_active":    _do_maximize_active,
    "switch_window":      _do_switch_window,
    "set_mode":           _do_set_mode,
    "load_pack":          _do_load_pack,
    "unload_pack":        _do_unload_pack,
    "list_packs":         _do_list_packs,
    "change_voice":       _do_change_voice,
    "list_voices":        _do_list_voices,
    "set_timer":          _do_set_timer,
    "list_timers":        _do_list_timers,
    "cancel_timers":      _do_cancel_timers,
    "add_task":           _do_add_task,
    "list_tasks":         _do_list_tasks,
    "done_task":          _do_done_task,
    "remove_task":        _do_remove_task,
    "clear_tasks":        _do_clear_tasks,
    "open_config":        _do_open_config,
    "open_log":           _do_open_log,
    "open_profile":       _do_open_profile,
    "get_weather":        _do_get_weather,
    "get_currency":       _do_get_currency,
    "delete_profile":     _do_delete_profile,
    "set_profile":        _do_set_profile,
    "get_profile":        _do_get_profile,
    "answer":             _do_answer,
    # === UIA ===
    "uia_read_window":    _do_uia_read_window,
    "uia_read_url":       _do_uia_read_url,
    "uia_read_tab":       _do_uia_read_tab,
    "uia_list_tabs":      _do_uia_list_tabs,
    "uia_close_tab":      _do_uia_close_tab,
    "uia_switch_tab":     _do_uia_switch_tab,
    "uia_click_button":   _do_uia_click_button,
    "uia_active_window":  _do_uia_active_window,
    "uia_menu":           _do_uia_menu,
}