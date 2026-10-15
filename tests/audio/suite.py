"""Strict, versioned audio scenarios. Expected text never reaches an ASR prompt."""

import hashlib
import json
import re
from pathlib import Path

SCHEMA = 1
ID = re.compile(r"[a-z0-9_-]{1,64}\Z")
DEFAULT_SUITE = Path(__file__).with_name("scenarios.json")


class Blocked(RuntimeError):
    """No valid measurement was made: exit 2, never an all-skipped success."""


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def safe_file(root, relative):
    if not isinstance(relative, str) or "\\" in relative:
        raise Blocked("Неверный относительный путь WAV")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise Blocked("WAV должен находиться внутри каталога корпуса")
    result = (Path(root) / rel).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise Blocked("WAV выходит из каталога корпуса")
    return result


def load_suite(path=DEFAULT_SUITE):
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema") != SCHEMA or not isinstance(data.get("scenarios"), list):
        raise Blocked("Неподдержанная схема аудиосценариев")
    if not 1 <= len(data["scenarios"]) <= 100:
        raise Blocked("Нужен непустой набор: не более 100 сценариев")
    seen = set()
    for case in data["scenarios"]:
        key = case.get("id", "")
        if not ID.fullmatch(key) or len(key) > 40 or key in seen:
            raise Blocked("Неверный или повторяющийся ID сценария")
        seen.add(key)
        turns = case.get("turns")
        if not isinstance(turns, list) or not 1 <= len(turns) <= 10:
            raise Blocked("В сценарии должно быть 1–10 ходов")
        for turn in turns:
            if set(turn) - {"text", "signal", "expect"}:
                raise Blocked("Неизвестное поле аудиохода")
            if ("text" in turn) == ("signal" in turn):
                raise Blocked("Укажи текст синтеза ИЛИ тестовый сигнал")
            if "text" in turn and (
                not isinstance(turn["text"], str) or not 1 <= len(turn["text"]) <= 500
            ):
                raise Blocked("Неверный текст аудиохода")
            if "signal" in turn and turn["signal"] not in {"silence", "noise"}:
                raise Blocked("Неподдержанный тестовый сигнал")
            expect = turn.get("expect")
            if (
                not isinstance(expect, dict)
                or not {"actions", "pending"} <= expect.keys()
            ):
                raise Blocked("Нужны ожидания actions/pending для каждого хода")
            if set(expect) - {
                "actions",
                "pending",
                "reply_contains",
                "speech",
                "handled",
            }:
                raise Blocked("Неизвестное поле ожидания")
            if expect["pending"] not in {None, "target", "time", "unit"}:
                raise Blocked("Неверный ожидаемый слот")
            if not isinstance(expect["actions"], list):
                raise Blocked("actions должен быть списком")
            for action in expect["actions"]:
                if not isinstance(action, dict) or action.get("action") not in {
                    "open",
                    "timer",
                }:
                    raise Blocked("Неподдержанное ожидаемое действие")
            for flag in ("speech", "handled"):
                if flag in expect and not isinstance(expect[flag], bool):
                    raise Blocked("speech/handled должны быть bool")
            if not isinstance(expect.get("reply_contains", ""), str):
                raise Blocked("reply_contains должен быть строкой")
    return data, fingerprint(raw)


def load_corpus(directory, suite, suite_hash):
    root = Path(directory)
    path = root / "corpus.json"
    if not path.is_file():
        raise Blocked("Корпус не подготовлен. Сначала запусти prepare")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA or data.get("suite_sha256") != suite_hash:
        raise Blocked("Сценарии изменились или корпус несовместим: повтори prepare")
    records = data.get("cases")
    if not isinstance(records, list) or not 1 <= len(records) <= 1200:
        raise Blocked("В корпусе нет кейсов")
    expected = {s["id"]: s for s in suite["scenarios"]}
    ids, covered = set(), set()
    for case in records:
        key = case.get("id", "")
        if not ID.fullmatch(key) or key in ids or case.get("scenario") not in expected:
            raise Blocked("Неверный/повторяющийся ID кейса корпуса")
        ids.add(key)
        covered.add(case["scenario"])
        turns = case.get("turns", [])
        if len(turns) != len(expected[case["scenario"]]["turns"]):
            raise Blocked("Число записей не совпадает с числом ходов")
        for turn in turns:
            wav = safe_file(root, turn.get("wav"))
            if not wav.is_file() or wav.stat().st_size > 4_000_000:
                raise Blocked("Нет WAV или превышен предел 4 МБ")
            if fingerprint(wav.read_bytes()) != turn.get("sha256"):
                raise Blocked("WAV изменён/повреждён: повтори prepare")
    if covered != set(expected):
        raise Blocked("Корпус покрывает не все сценарии")
    return records
