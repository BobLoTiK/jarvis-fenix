"""Выбор backend'а AEC: свой (`native`) или WebRTC (`webrtc`).

По умолчанию — `native` (`jarvis/echo.py`), поведение не меняется. `webrtc`
включается только явно и только если пакет реально стоит: иначе честно
остаёмся на native и пишем причину, а не делаем вид, что эхо подавлено.
Пакет в зависимости не добавлен — это решение человека (лицензия, размер,
сборка установщика).
"""

import importlib
import logging
from dataclasses import dataclass

log = logging.getLogger("jarvis.aec_backend")

BACKENDS = ("native", "webrtc")
WEBRTC_MODULES = ("webrtc_audio_processing", "pywebrtc_audio")


@dataclass(frozen=True)
class BackendChoice:
    """Что выбрали на самом деле и почему."""

    name: str
    requested: str
    reason: str

    @property
    def fallback(self) -> bool:
        return self.name != self.requested


def resolve(config, *, importer=None) -> BackendChoice:
    """`aec_backend` из конфига → фактический backend с причиной."""
    requested = config.get("aec_backend", "native")
    if not isinstance(requested, str) or requested not in BACKENDS:
        return BackendChoice("native", "native",
                             f"неизвестный aec_backend={requested!r}, оставлен native")
    if requested == "native":
        return BackendChoice("native", "native", "свой AEC (эталон из RenderTap)")
    load = importer or importlib.import_module
    for module in WEBRTC_MODULES:
        try:
            load(module)
        except ImportError:
            continue
        except Exception:
            log.debug("AEC: проверка %s упала", module, exc_info=True)
            continue
        return BackendChoice("webrtc", "webrtc", f"WebRTC AEC доступен ({module})")
    return BackendChoice("native", "webrtc",
                         "WebRTC AEC недоступен: пакет не установлен — работаем на native")
