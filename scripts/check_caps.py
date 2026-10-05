"""Проверка возможностей системы — запускается из install.bat.

Пишет system_caps.json:
    {
        "volume":     {"available": true,  "method": "volume_percent"},
        "brightness": {"available": true,  "method": "sbc"},
        "layout":     {"available": true,  "method": "sendinput"},
        "checked_at": 1791210000.0
    }

Зачем:
    API pycaw / screen-brightness-control меняется между версиями.
    Проверяем ОДИН РАЗ при установке, а не в рантайме.

Если что-то не работает — видно сразу при установке.
"""
import json
import logging
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "system_caps.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("check_caps")


def check_volume() -> dict:
    """Проверяет громкость. Возвращает {'available': bool, 'method': str}."""
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()

        # Способ 1: volume_percent (pycaw >= 2026)
        if hasattr(device, "volume_percent"):
            try:
                _ = device.volume_percent
                return {"available": True, "method": "volume_percent"}
            except Exception:
                pass

        # Способ 2: EndpointVolume
        if hasattr(device, "EndpointVolume"):
            try:
                _ = device.EndpointVolume.GetMasterVolumeLevelScalar()
                return {"available": True, "method": "endpoint_volume"}
            except Exception:
                pass

        # Способ 3: Activate
        if hasattr(device, "Activate"):
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import IAudioEndpointVolume
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol = cast(interface, POINTER(IAudioEndpointVolume))
                _ = vol.GetMasterVolumeLevelScalar()
                return {"available": True, "method": "activate"}
            except Exception:
                pass

        return {"available": False, "method": "none", "reason": "no known API"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}


def check_brightness() -> dict:
    """Проверяет яркость."""
    try:
        import screen_brightness_control as sbc
        values = sbc.get_brightness()
        if values:
            return {"available": True, "method": "sbc"}
        return {"available": False, "method": "none", "reason": "no monitors"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}


def check_layout() -> dict:
    """Проверяет раскладку (SendInput)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        _ = user32.SendInput
        return {"available": True, "method": "sendinput"}
    except Exception as e:
        return {"available": False, "method": "none", "reason": str(e)[:80]}


def main() -> int:
    log.info("=" * 60)
    log.info("  Проверка возможностей системы")
    log.info("=" * 60)

    caps = {
        "volume": check_volume(),
        "brightness": check_brightness(),
        "layout": check_layout(),
        "checked_at": time.time(),
    }

    log.info("")
    for name, info in caps.items():
        if name == "checked_at":
            continue
        mark = "[OK]  " if info.get("available") else "[FAIL]"
        reason = f"  ({info.get('reason', '')})" if not info.get("available") else ""
        log.info("%s %-12s %s%s", mark, name, info.get("method", "?"), reason)

    OUTPUT.write_text(
        json.dumps(caps, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("")
    log.info("Сохранено: %s", OUTPUT)
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())