"""Скачивание и распаковка модели Vosk для русского языка (~45 МБ).

Модель всегда лежит в ASCII-пути (C:\\ProgramData\\Phoenix\\models).
Vosk (C++ на Kaldi) ломается на не-ASCII путях — поэтому копируем
в safe-путь при первом обращении.
"""

import logging
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from jarvis import paths

log = logging.getLogger("jarvis.model")

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"

# Required payload of this specific Vosk model, not merely its directory names.
REQUIRED_MODEL_FILES = (
    "am/final.mdl",
    "conf/mfcc.conf",
    "conf/model.conf",
    "graph/disambig_tid.int",
    "graph/Gr.fst",
    "graph/HCLr.fst",
    "graph/phones/word_boundary.int",
    "ivector/final.dubm",
    "ivector/final.ie",
    "ivector/final.mat",
    "ivector/global_cmvn.stats",
    "ivector/online_cmvn.conf",
    "ivector/splice.conf",
)


def model_is_ready(model_dir: Path) -> bool:
    """Reject interrupted copies/extractions and empty required files."""
    try:
        return all(
            (model_dir / name).is_file() and (model_dir / name).stat().st_size > 0
            for name in REQUIRED_MODEL_FILES
        )
    except OSError:
        return False


def _extract_model_archive(archive_path: Path, model_dir: Path) -> None:
    """Extract only model members; reject traversal, Windows drives and links."""
    base = model_dir.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if (not parts or parts[0] != MODEL_NAME or name.startswith("/")
                    or any(part == ".." or ":" in part or part.endswith((" ", "."))
                           for part in parts)
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError(f"Небезопасный путь в ZIP модели: {member.filename!r}")
            if len(parts) == 1:
                if not name.endswith("/"):
                    raise ValueError("Корень ZIP модели должен быть папкой")
                continue
            target = model_dir.joinpath(*parts[1:]).resolve()
            if not target.is_relative_to(base):
                raise ValueError(f"Путь вне папки модели: {member.filename!r}")
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)


def _publish_model(staged: Path, target: Path) -> Path:
    """Publish a complete same-volume staging directory, restoring on failure."""
    if not model_is_ready(staged):
        raise RuntimeError("Модель Vosk неполная: отсутствуют обязательные файлы")
    if model_is_ready(target):
        return target

    backup = staged.parent / "previous-model"
    had_previous = target.exists() or target.is_symlink()
    if had_previous:
        target.rename(backup)
    try:
        staged.replace(target)
    except OSError:
        # A concurrent installer may already have published a complete model.
        if model_is_ready(target):
            return target
        if had_previous:
            try:
                backup.replace(target)
            except OSError:
                log.exception("Не удалось вернуть предыдущий каталог модели")
        raise
    log.info("Модель Vosk готова: %s", target)
    return target


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


def ensure_model(
    local_models_dir: Path | None = None,
    *,
    reporthook: Callable[[int, int, int], None] | None = None,
) -> Path:
    """Возвращает путь к модели Vosk в ASCII-пути.

    Аргумент local_models_dir — необязательный. Если модель есть там,
    но путь не-ASCII, копируем её в safe-путь.
    """
    safe_dir = paths.program_models_dir() / MODEL_NAME

    if model_is_ready(safe_dir):
        log.info("Модель Vosk готова: %s", safe_dir)
        return safe_dir

    safe_dir.parent.mkdir(parents=True, exist_ok=True)
    # Unique same-volume staging avoids partial final directories and shared ZIPs.
    with tempfile.TemporaryDirectory(
        prefix=f".{MODEL_NAME}-", dir=safe_dir.parent, ignore_cleanup_errors=True
    ) as temp:
        staged = Path(temp) / "model"
        if local_models_dir is not None:
            local_model = local_models_dir / MODEL_NAME
            if model_is_ready(local_model):
                log.info("Копирую модель Vosk: %s → %s", local_model, safe_dir)
                try:
                    shutil.copytree(local_model, staged)
                except OSError:
                    log.exception("Не удалось скопировать модель; пробую загрузку")
                    if staged.exists():
                        shutil.rmtree(staged)
                else:
                    return _publish_model(staged, safe_dir)

        zip_path = Path(temp) / "model.zip"
        log.info("Скачиваю модель Vosk: %s", MODEL_URL)
        try:
            urllib.request.urlretrieve(
                MODEL_URL, zip_path,
                reporthook=reporthook if reporthook is not None else _progress,
            )
            if sys.stdout is not None:
                sys.stdout.write("\n")
            staged.mkdir()
            _extract_model_archive(zip_path, staged)
            return _publish_model(staged, safe_dir)
        except Exception:
            log.exception("Не удалось подготовить модель Vosk")
            raise