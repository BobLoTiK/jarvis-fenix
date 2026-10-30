"""Секреты Феникса: ключи облачных провайдеров, зашифрованные Windows DPAPI.

Почему так, а не «хешировать»:

    Хеш необратим. Хешировать можно пароль, который мы только сравниваем.
    API-ключ нужно отправлять провайдеру в открытом виде, поэтому его надо
    именно шифровать — обратимо, но так, чтобы без вашей учётной записи
    Windows файл не расшифровывался.

    DPAPI (CryptProtectData) привязывает шифрование к текущему пользователю
    Windows: копия файла на другом компьютере или под другой учётной записью
    не расшифруется. Дополнительно подмешивается энтропия с именем продукта,
    чтобы блоб не открывался чужим приложением от того же пользователя.

    В config.json ключа нет вообще — там только несекретные параметры
    (провайдер, адрес, модель). Значение никогда не логируется: в журнал
    попадает имя секрета, длина и отпечаток SHA-256, но не сам ключ.

Отпечаток (fingerprint) — это SHA-256 от значения, первые 8 hex-символов.
Он нужен, чтобы человек мог сверить «тот ли ключ сохранён», не показывая
ключ ни на экране, ни в логе.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import re
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("jarvis.secrets_store")

CLOUD_LLM_KEY = "cloud_llm_key"

# Энтропия DPAPI: тот же пользователь, но другое приложение — уже не расшифрует.
_ENTROPY = b"Phoenix/cloud-llm/v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_MAX_SECRET_BYTES = 8192


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes):
    buffer = ctypes.create_string_buffer(data, len(data))
    keep = (buffer, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return _Blob(len(data), keep[1]), keep


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    """CryptProtectData / CryptUnprotectData с фиксированной энтропией."""
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_in, keep_in = _to_blob(data)
    blob_entropy, keep_entropy = _to_blob(_ENTROPY)
    blob_out = _Blob()

    if protect:
        fn = crypt32.CryptProtectData
        # (pDataIn, szDataDescr LPCWSTR, pEntropy, pvReserved, pPrompt, flags, pDataOut)
        argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR,
                    ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                    wintypes.DWORD, ctypes.POINTER(_Blob)]
    else:
        fn = crypt32.CryptUnprotectData
        # (pDataIn, ppszDataDescr LPWSTR*, pEntropy, pvReserved, pPrompt, flags, pDataOut)
        argtypes = [ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR),
                    ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                    wintypes.DWORD, ctypes.POINTER(_Blob)]
    fn.argtypes = argtypes
    fn.restype = wintypes.BOOL

    ok = fn(ctypes.byref(blob_in), None, ctypes.byref(blob_entropy), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    del keep_in, keep_entropy  # буферы нужны были только на время вызова
    if not ok:
        code = ctypes.get_last_error()
        raise OSError(code, "DPAPI не смог обработать секрет")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Секреты Феникса хранятся через Windows DPAPI: нужна Windows.")


def _path(name: str) -> Path:
    from jarvis import paths

    safe = re.sub(r"[^a-z0-9_]+", "_", str(name).lower()).strip("_")[:40]
    if not safe:
        raise ValueError("Пустое имя секрета")
    return paths.secrets_dir() / f"{safe}.bin"


def fingerprint(value: str) -> str:
    """Отпечаток значения для сверки глазами. Не сам ключ и не его слабая часть."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:8]


def save_secret(name: str, value: str) -> bool:
    """Шифрует и атомарно записывает секрет. Значение не логируется."""
    _require_windows()
    value = str(value or "").strip()
    if not value:
        raise ValueError("Пустой секрет сохранять нечего")
    if len(value.encode("utf-8")) > _MAX_SECRET_BYTES:
        raise ValueError("Секрет слишком длинный")
    blob = _dpapi(value.encode("utf-8"), protect=True)
    path = _path(name)
    temp = path.with_suffix(".tmp")
    try:
        temp.write_bytes(blob)
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
    log.info("Секрет %s сохранён (DPAPI, отпечаток %s)", name, fingerprint(value))
    return True


def load_secret(name: str) -> str | None:
    """Расшифровывает секрет. None — файла нет или он от другой учётной записи."""
    _require_windows()
    path = _path(name)
    if not path.exists():
        return None
    try:
        raw = _dpapi(path.read_bytes(), protect=False)
        return raw.decode("utf-8")
    except (OSError, ValueError):
        # Частый случай: файл скопирован с другой машины/пользователя.
        log.warning("Секрет %s не расшифрован: файл от другой учётной записи?", name)
        return None


def has_secret(name: str) -> bool:
    return _path(name).exists()


def secret_fingerprint(name: str) -> str | None:
    value = load_secret(name)
    return fingerprint(value) if value else None


def delete_secret(name: str) -> bool:
    """Удаляет секрет. True — файла больше нет."""
    path = _path(name)
    if not path.exists():
        return True
    try:
        path.unlink()
    except OSError:
        log.exception("Не удалось удалить секрет %s", name)
        return False
    log.info("Секрет %s удалён", name)
    return True
