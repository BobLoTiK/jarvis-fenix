"""Проверка возможностей системы — запускается из install.bat.

Пишет %APPDATA%\\Phoenix\\system_caps.json (не данные сборщика):
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
import argparse
import os
import tempfile
import json
import logging
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from jarvis import paths
OUTPUT = paths.system_caps_path()

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

def check_cpu() -> dict:
    """Определяет категорию CPU для рекомендации Piper.

    Возвращает: категория (weak/normal/strong) + рекомендация (medium/high).
    Никаких конкретных моделей CPU — только количество ядер/потоков.
    """
    try:
        import psutil
    except ImportError:
        return {"available": False, "reason": "psutil не установлен"}

    try:
        cores = psutil.cpu_count(logical=False) or 0
        threads = psutil.cpu_count(logical=True) or 0

        if cores >= 6 and threads >= 12:
            power = "strong"
            recommended_piper = "medium"  # CPU count cannot prove voice/model availability or quality
        elif cores >= 4 and threads >= 8:
            power = "normal"
            recommended_piper = "medium"
        else:
            power = "weak"
            recommended_piper = "medium"

        return {
            "available": True,
            "cores": cores,
            "threads": threads,
            "power": power,
            "recommended_piper": recommended_piper,
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}

def write_caps(caps, destination=None):
    destination = Path(destination or OUTPUT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="caps-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(caps, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def caps_valid(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return isinstance(data,dict) and all(isinstance(data.get(k),dict) for k in ('volume','brightness','layout','cpu'))
    except (OSError, ValueError):
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--if-missing", action="store_true")
    args = parser.parse_args(argv)
    if args.if_missing and caps_valid(OUTPUT):
        log.info("Локальная диагностика уже есть: %s", OUTPUT)
        return 0
    log.info("=" * 60)
    log.info("  Проверка возможностей системы")
    log.info("=" * 60)

    caps = {
        "volume": check_volume(),
        "brightness": check_brightness(),
        "layout": check_layout(),
        "cpu": check_cpu(),
        "checked_at": time.time(),
    }

    log.info("")
    for name, info in caps.items():
        if name == "checked_at":
            continue
        mark = "[OK]  " if info.get("available") else "[FAIL]"

        if name == "cpu":
            # Специальный вывод для CPU
            if info.get("available"):
                log.info(
                    "%s %-12s %s ядер / %s потоков → рекомендация: %s",
                    mark, name,
                    info.get("cores"), info.get("threads"),
                    info.get("recommended_piper", "medium"),
                )
            else:
                log.info("%s %-12s %s", mark, name, info.get("reason", "?"))
            continue

        reason = f"  ({info.get('reason', '')})" if not info.get("available") else ""
        log.info("%s %-12s %s%s", mark, name, info.get("method", "?"), reason)

    write_caps(caps)
    log.info("")
    log.info("Сохранено: %s", OUTPUT)
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())