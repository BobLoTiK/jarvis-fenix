"""Скачивание и распаковка модели Vosk для русского языка (~45 МБ).

Модель всегда лежит в ASCII-пути (C:\\ProgramData\\Phoenix\\models).
Vosk (C++ на Kaldi) ломается на не-ASCII путях — поэтому копируем
в safe-путь при первом обращении.
"""

import logging
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from jarvis import paths

log = logging.getLogger("jarvis.model")

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


def _progress(blocks: int, block_size: int, total: int) -> None:
    """Прогресс-бар скачивания модели.

    ВАЖНО: под pythonw.exe sys.stdout = None (нет консоли).
    Проверяем — если stdout нет, тихо пропускаем прогресс.
    """
    if total <= 0:
        return
    if sys.stdout is None:
        return
    try:
        pct = min(100, blocks * block_size * 100 // total)
        sys.stdout.write(f"\rСкачивание модели: {pct}%")
        sys.stdout.flush()
    except Exception:
        pass


def ensure_model(local_models_dir: Path | None = None) -> Path:
    """Возвращает путь к модели Vosk в ASCII-пути.

    Аргумент local_models_dir — необязательный. Если модель есть там,
    но путь не-ASCII, копируем её в safe-путь.
    """
    safe_dir = paths.program_models_dir() / MODEL_NAME

    if safe_dir.exists() and (safe_dir / "am").exists():
        log.info("Модель Vosk готова: %s", safe_dir)
        return safe_dir

    # Если есть локальная копия (например, C:\jarvis\models\...) — копируем
    if local_models_dir is not None:
        local_model = local_models_dir / MODEL_NAME
        if local_model.exists() and (local_model / "am").exists():
            log.info("Копирую модель Vosk: %s → %s", local_model, safe_dir)
            try:
                if safe_dir.exists():
                    shutil.rmtree(safe_dir)
                shutil.copytree(local_model, safe_dir)
                log.info("Модель скопирована")
                return safe_dir
            except Exception:
                log.exception("Не удалось скопировать модель")

    # Скачиваем
    safe_dir.parent.mkdir(parents=True, exist_ok=True)
    zip_path = safe_dir.parent / f"{MODEL_NAME}.zip"

    log.info("Скачиваю модель Vosk: %s", MODEL_URL)
    try:
        urllib.request.urlretrieve(MODEL_URL, zip_path, reporthook=_progress)
        if sys.stdout is not None:
            sys.stdout.write("\n")
    except Exception:
        log.exception("Не удалось скачать модель Vosk")
        raise

    log.info("Распаковка модели...")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            # В архиве одна папка vosk-model-small-ru-0.22/.
            # Распаковываем её СОДЕРЖИМОЕ в safe_dir, без вложенности.
            for member in zf.namelist():
                parts = member.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue
                target = safe_dir / parts[1]
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
    finally:
        zip_path.unlink(missing_ok=True)

    if not safe_dir.exists():
        raise RuntimeError(f"После распаковки не найдена папка {safe_dir}")
    log.info("Модель готова: %s", safe_dir)
    return safe_dir