"""Открытие приложений / сайтов / папок / профиля — без LLM.

`open_profile_fast` идёт ВЫШЕ `open_fast` в реестре,
чтобы «открой профиль» не улетело в open_app.
"""

import logging
import re

from jarvis import actions, profile
from jarvis.intents.execute import _do_open, _do_close

log = logging.getLogger("jarvis.intents")


def open_fast(handler, cmd: str) -> str | None:
    """«открой X», «запусти X», «включи X», «врубай X» → open."""
    m = re.match(r"^(?:открой|запусти|врубай|включи|открывай)\s+(.+)$", cmd)
    if not m:
        return None
    target = m.group(1).strip()
    if not target:
        return None
    # Защита: «открой профиль» — не наше дело (open_profile_fast выше).
    if "профиль" in target:
        return None
    return _do_open(handler, target)


def open_profile_fast(handler, cmd: str) -> str | None:
    """«открой профиль» → profile.json в Notepad++ / VS Code / системе.

    Опционально: «открой профиль в вс код», «открой профиль в блокноте».
    """
    if not re.search(r"откр\w*\s+профиль", cmd):
        return None

    prefer = "auto"
    if re.search(r"\bв\s+(vs\s*code|вс\s*код|вскод|code)\b", cmd):
        prefer = "vscode"
    elif re.search(r"\bв\s+(notepad\+\+|нотпад\s*плюс|нотепад)\b", cmd):
        prefer = "notepad++"
    elif re.search(r"\bв\s+(блокнот|notepad)\b", cmd):
        prefer = "system"
    elif re.search(r"\bв\s+(системн|обычн)\w*\s+редактор", cmd):
        prefer = "system"

    prof_path = profile.profile_path()
    if not prof_path.exists():
        return f"Профиль не найден: {prof_path.name}"

    ok = actions.open_in_editor(prof_path, prefer=prefer)
    if ok:
        editor_name = {
            "auto": "редакторе",
            "vscode": "VS Code",
            "notepad++": "Notepad++",
            "system": "системном редакторе",
        }.get(prefer, "редакторе")
        return f"Открываю профиль в {editor_name}."
    return "Не удалось открыть профиль."