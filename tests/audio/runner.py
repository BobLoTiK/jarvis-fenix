"""CLI orchestration; blocked resources always exit 2, never a fake pass."""

import argparse
import platform
import sys
import time
from pathlib import Path

from tests.audio.corpus import framed_pcm, mono16k, prepare, write_json
from tests.audio.runtime import Engine, check_expected, preflight
from tests.audio.suite import DEFAULT_SUITE, Blocked, load_corpus, load_suite, safe_file

ROOT = Path(__file__).resolve().parents[2]


def run(
    suite,
    suite_hash,
    directory,
    *,
    engine_factory=Engine,
    models=None,
    asr="hybrid",
    no_vad=False,
    device="cpu",
    selected=None,
    include_transcripts=False,
):
    cases = load_corpus(directory, suite, suite_hash)
    selected_cases = [
        c for c in cases if selected is None or selected in {c["id"], c["scenario"]}
    ]
    if not selected_cases:
        raise Blocked("Фильтр не выбрал ни одного кейса")
    scenarios = {s["id"]: s for s in suite["scenarios"]}
    started = time.perf_counter()
    report = {
        "schema": 1,
        "status": "running",
        "asr": asr,
        "python": platform.python_version(),
        "platform": platform.system(),
        "suite_sha256": suite_hash,
        "selected_cases": len(selected_cases),
        "total_cases": len(cases),
        "coverage": {
            "vad": not no_vad,
            "vosk_endpoint": True,
            "whisper": asr == "hybrid",
            "production_process": True,
            "command_domain": ["open", "timer", "cancel"],
            "physical_mic": False,
            "playback": False,
            "llm": False,
            "full_command_registry": False,
            "password": False,
        },
        "cases": [],
    }
    with engine_factory(models, asr=asr, no_vad=no_vad, device=device) as engine:
        for case in selected_cases:
            result = {
                "id": case["id"],
                "source": case["source"],
                "variant": case["variant"],
                "status": "pass",
                "turns": [],
            }
            with engine.new_case() as sandbox:
                for wav_info, turn in zip(
                    case["turns"], scenarios[case["scenario"]]["turns"]
                ):
                    wav = safe_file(directory, wav_info["wav"]).read_bytes()
                    actual = engine.replay(
                        framed_pcm(mono16k(wav)),
                        sandbox,
                        include_transcripts=include_transcripts,
                    )
                    errors = check_expected(
                        actual, turn["expect"], len(actual["endpoints"])
                    )
                    # Files/hashes identify local recordings without exporting raw ASR text.
                    saved = {k: v for k, v in actual.items() if k != "replies"}
                    saved.update(wav_sha256=wav_info["sha256"], errors=errors)
                    if include_transcripts:
                        saved["replies"] = actual["replies"]
                    else:
                        # Targets/reminder text can also contain recognized private speech.
                        saved["actions"] = [
                            {k: v for k, v in a.items() if k in {"action", "seconds"}}
                            for a in actual["actions"]
                        ]
                    result["turns"].append(saved)
                    if errors:
                        result["status"] = "fail"
                        break
            report["cases"].append(result)
    report["failed"] = sum(c["status"] != "pass" for c in report["cases"])
    report["passed"] = len(report["cases"]) - report["failed"]
    report["status"] = "fail" if report["failed"] else "pass"
    report["wall_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Офлайн-аудиорегрессии Феникса: без микрофона и реальных действий"
    )
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument(
        "--workdir", type=Path, help="Локальный каталог WAV и отчётов (не репозиторий)"
    )
    parser.add_argument(
        "--voices",
        default="auto",
        help="prepare: auto или Pavel,Irina; только установленные русские голоса",
    )
    parser.add_argument("--variants", default="clean,quiet,noise")
    parser.add_argument(
        "--recordings",
        type=Path,
        help="prepare: локальные <scenario>/01.wav; все речевые ходы обязательны",
    )
    parser.add_argument("--asr", choices=["hybrid", "vosk"], default="hybrid")
    parser.add_argument("--vosk-model", type=Path)
    parser.add_argument(
        "--whisper-model",
        type=Path,
        help="Полная локальная CTranslate2-папка, не имя для скачивания",
    )
    parser.add_argument("--device", choices=["cpu", "auto", "cuda"], default="cpu")
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="Диагностический профиль без VAD, не полная проверка",
    )
    parser.add_argument(
        "--case",
        help="run: только указанный ID сценария/кейса; охват отражается в отчёте",
    )
    parser.add_argument(
        "--include-transcripts",
        action="store_true",
        help="Явно сохранить распознанные фразы в локальный отчёт",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.workdir is None:
        from jarvis.paths import audio_regression_dir

        args.workdir = audio_regression_dir()
    report_path = args.report or args.workdir / "reports" / "latest.json"
    try:
        suite, sha = load_suite(args.suite)
        if args.command == "prepare":
            data = prepare(
                suite,
                sha,
                args.workdir,
                voices=tuple(args.voices.split(",")),
                variants=tuple(args.variants.split(",")),
                recordings=args.recordings,
            )
            print(
                f"Корпус готов: {len(data['cases'])} кейсов, {sum(len(c['turns']) for c in data['cases'])} аудиоходов."
            )
            print(f"WAV остаются локально: {args.workdir}")
            return 0
        # Validate the whole corpus before loading expensive models.
        load_corpus(args.workdir, suite, sha)
        models = preflight(
            ROOT,
            asr=args.asr,
            no_vad=args.no_vad,
            vosk_model=args.vosk_model,
            whisper_model=args.whisper_model,
        )
        result = run(
            suite,
            sha,
            args.workdir,
            models=models,
            asr=args.asr,
            no_vad=args.no_vad,
            device=args.device,
            selected=args.case,
            include_transcripts=args.include_transcripts,
        )
        write_json(report_path, result)
        print(
            f"{result['status'].upper()}: {result['passed']} passed, {result['failed']} failed; {result['selected_cases']}/{result['total_cases']} кейсов."
        )
        print(
            f"Профиль: {args.asr}, VAD {'OFF (диагностика)' if args.no_vad else 'ON'}; микрофон/озвучка не проверялись."
        )
        for case in result["cases"]:
            if case["status"] == "fail":
                print(case["id"] + ": " + "; ".join(case["turns"][-1]["errors"]))
        print(f"Отчёт: {report_path}")
        return 1 if result["failed"] else 0
    except Exception as error:  # noqa: BLE001 -- CLI reports any model failure as BLOCKED
        # No traceback flood and no silent skip when a runtime/model is missing.
        result = {
            "schema": 1,
            "status": "blocked",
            "passed": 0,
            "reason": f"{type(error).__name__}: {str(error)[:600]}",
        }
        try:
            write_json(report_path, result)
        except OSError:
            pass
        print("BLOCKED (не pass): " + result["reason"], file=sys.stderr)
        print(f"Отчёт: {report_path}", file=sys.stderr)
        return 2
