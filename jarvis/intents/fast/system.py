"""Системные команды: раскладка, громкость, яркость."""

import re

from jarvis import actions, history


def system_fast(handler, cmd: str) -> str | None:
    reply = _layout(cmd)
    if reply:
        return reply
    reply = _volume(cmd)
    if reply:
        return reply
    reply = _brightness(cmd)
    if reply:
        return reply
    return None


# =================================================================
# Раскладка
# =================================================================

def _layout(cmd: str) -> str | None:
    if not re.search(r"раскладк", cmd):
        return None

    if re.search(r"(переключ|смени|поменяй|следующ)", cmd):
        ok = actions.switch_layout()
        if ok:
            history.push({"action": "switch_layout"})
        return "Переключаю раскладку." if ok else "Не удалось переключить."
    if re.search(r"(русск|ru)", cmd):
        ok = actions.set_layout_ru()
        return "Русская раскладка." if ok else "Не удалось."
    if re.search(r"(англ|english|en)", cmd):
        ok = actions.set_layout_en()
        return "Английская раскладка." if ok else "Не удалось."
    if re.search(r"(какая|текущ|что)", cmd):
        layout = actions.get_layout()
        if layout == "ru":
            return "Сейчас русская раскладка."
        if layout == "en":
            return "Сейчас английская раскладка."
        return "Не смог определить раскладку."
    return None


# =================================================================
# Громкость
# =================================================================

def _volume(cmd: str) -> str | None:
    # «громкость 50»
    m = re.search(r"громкость\s+(?:на\s+)?(\d+)", cmd)
    if m:
        pct = int(m.group(1))
        prev = actions.get_volume()
        ok = actions.set_volume(pct)
        if ok:
            history.push({"action": "set_volume", "prev_value": prev})
        return f"Громкость: {pct}%." if ok else "Не удалось."

    # «сделай на 10 потише» (№69)
    m = re.search(
        r"(?:сделай|поставь|сделай\s+пожалуйста)\s+(?:на\s+)?(\d+)\s+(потише|тише|погромче|громче)",
        cmd,
    )
    if m:
        delta = int(m.group(1))
        direction = m.group(2)
        if "тише" in direction:
            delta = -delta
        prev = actions.get_volume()
        if prev is not None:
            new_vol = max(0, min(100, prev + delta))
            ok = actions.set_volume(new_vol)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {new_vol}%." if ok else "Не удалось."

    # «потише» / «погромче» (без числа, ±10)
    if re.search(r"\b(потише|тише)\b", cmd):
        prev = actions.get_volume()
        if prev is not None:
            new_vol = max(0, prev - 10)
            ok = actions.set_volume(new_vol)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {new_vol}%." if ok else "Не удалось."

    if re.search(r"\b(погромче|громче)\b", cmd):
        prev = actions.get_volume()
        if prev is not None:
            new_vol = min(100, prev + 10)
            ok = actions.set_volume(new_vol)
            if ok:
                history.push({"action": "set_volume", "prev_value": prev})
            return f"Громкость: {new_vol}%." if ok else "Не удалось."

    # «какая громкость»
    if (re.search(r"(какая|текущ|узнай)\s+громкость", cmd)
            or cmd in {"какая громкость", "текущая громкость"}):
        vol = actions.get_volume()
        return f"Громкость: {vol}%." if vol is not None else "Не смог узнать."

    return None


# =================================================================
# Яркость
# =================================================================

def _brightness(cmd: str) -> str | None:
    m = re.search(r"яркость\s+(?:на\s+)?(\d+)", cmd)
    if m:
        pct = int(m.group(1))
        prev = actions.get_brightness()
        ok = actions.set_brightness(pct)
        if ok:
            history.push({"action": "set_brightness", "prev_value": prev})
        return f"Яркость: {pct}%." if ok else "Не удалось."

    if (re.search(r"(какая|текущ|узнай)\s+яркость", cmd)
            or cmd in {"какая яркость", "текущая яркость"}):
        br = actions.get_brightness()
        return f"Яркость: {br}%." if br is not None else "Не смог узнать."

    return None