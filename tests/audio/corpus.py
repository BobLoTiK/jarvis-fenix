"""Local-only WAV preparation. No playback, recordings or model downloads."""

import json
import os
import tempfile
from pathlib import Path

import numpy as np

from jarvis.audio_output import decode_wav, encode_wav
from tests.audio.suite import Blocked, fingerprint, safe_file

RATE = 16000
VARIANTS = ("clean", "quiet", "noise")


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def mono16k(wav):
    audio, rate = decode_wav(wav)
    if not len(audio) or len(audio) / rate > 30:
        raise Blocked("Нужен непустой WAV не длиннее 30 секунд")
    mono = audio.mean(axis=1)
    if rate != RATE:
        count = max(1, round(len(mono) * RATE / rate))
        mono = np.interp(np.arange(count) * rate / RATE, np.arange(len(mono)), mono)
    return mono.astype(np.float32)


def transform(audio, variant, seed=42):
    if variant not in VARIANTS:
        raise Blocked("Неизвестный вариант аудио")
    audio = np.asarray(audio, dtype=np.float32).copy()
    if variant == "quiet":
        audio *= 10 ** (-12 / 20)
    elif variant == "noise":
        rms = float(np.sqrt(np.mean(audio**2)))
        noise = np.random.default_rng(seed).normal(size=len(audio))
        nrms = float(np.sqrt(np.mean(noise**2)))
        if nrms:
            audio += noise * (rms / nrms * 10 ** (-20 / 20))
    return np.clip(audio, -0.999, 0.999).astype(np.float32)


def framed_pcm(audio, seed=42):
    """Known padding, not measured speech-end latency; dither avoids dead-mic mode."""
    rng = np.random.default_rng(seed)
    prefix = rng.normal(0, 15 / 32768, round(0.512 * RATE))
    tail = rng.normal(0, 15 / 32768, round(2.304 * RATE))
    stream = np.concatenate([prefix, audio, tail])
    return (np.clip(stream, -1, 1) * 32767).astype("<i2").tobytes()


class LocalSynth:
    """Optional test-only Windows WAV generator; never a live TTS engine."""

    def __init__(self, voice="auto"):
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer

        russian = [
            v
            for v in SpeechSynthesizer.all_voices
            if v.language.lower().startswith("ru")
        ]
        selected = next(
            (
                v
                for v in russian
                if voice == "auto" or voice.lower() in v.display_name.lower()
            ),
            None,
        )
        if selected is None:
            raise Blocked("Нет запрошенного русского системного голоса Windows")
        self.name = selected.display_name
        self._voice = selected

    async def _synthesize(self, text):
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader
        synth = SpeechSynthesizer()
        synth.voice = self._voice
        stream = await synth.synthesize_text_to_stream_async(text)
        reader = DataReader(stream.get_input_stream_at(0))
        try:
            await reader.load_async(stream.size)
            return bytes(reader.read_buffer(stream.size))
        finally:
            reader.close()
            stream.close()
            synth.close()

    def __call__(self, text):
        import asyncio
        return asyncio.run(self._synthesize(text))


def prepare(
    suite,
    suite_hash,
    directory,
    *,
    voices=("auto",),
    variants=VARIANTS,
    recordings=None,
    synth_factory=None,
):
    directory = Path(directory)
    synth_factory = synth_factory or LocalSynth
    if not voices or len(set(voices)) != len(voices) or len(voices) > 4:
        raise Blocked("Укажи 1–4 разных голоса")
    if (
        not variants
        or len(set(variants)) != len(variants)
        or set(variants) - set(VARIANTS)
    ):
        raise Blocked("Варианты: clean, quiet, noise; без повторов")
    if recordings:
        voices = ("recorded",)
    cases = []
    for voice in voices:
        if voice not in {"auto", "Pavel", "Irina", "recorded"}:
            raise Blocked("Поддержаны auto, Pavel, Irina или --recordings")
        synth = None if recordings else synth_factory(voice)
        cache = {}
        for scenario in suite["scenarios"]:
            originals = []
            for index, turn in enumerate(scenario["turns"], 1):
                if "signal" in turn:
                    audio = np.zeros(RATE, dtype=np.float32)
                    if turn["signal"] == "noise":
                        audio = (
                            np.random.default_rng(42)
                            .normal(0, 100 / 32768, RATE)
                            .astype(np.float32)
                        )
                elif recordings:
                    source = safe_file(recordings, f"{scenario['id']}/{index:02d}.wav")
                    if not source.is_file():
                        raise Blocked(
                            f"Нет записи {scenario['id']}/{index:02d}.wav; синтез не подставляется"
                        )
                    if source.stat().st_size > 12_000_000:
                        raise Blocked("Исходный WAV слишком большой")
                    audio = mono16k(source.read_bytes())
                else:
                    text = turn["text"]
                    if text not in cache:
                        cache[text] = mono16k(synth(text))
                    audio = cache[text]
                originals.append(audio)
            for variant in variants:
                case = {
                    "id": f"{scenario['id']}--{voice.lower()}--{variant}",
                    "scenario": scenario["id"],
                    "variant": variant,
                    "source": "recorded" if recordings else "synthetic",
                    "voice": "recorded"
                    if recordings
                    else getattr(synth, "name", voice),
                    "turns": [],
                }
                for audio in originals:
                    wav = encode_wav(transform(audio, variant)[:, None], RATE)
                    sha = fingerprint(wav)
                    relative = f"wav/{sha}.wav"
                    atomic_write(directory / relative, wav)
                    case["turns"].append({"wav": relative, "sha256": sha})
                cases.append(case)
    manifest = {"schema": 1, "suite_sha256": suite_hash, "cases": cases}
    # The old manifest stays valid if preparation fails partway through.
    write_json(directory / "corpus.json", manifest)
    return manifest
