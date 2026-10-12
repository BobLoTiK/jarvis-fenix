"""Бенчмарк VAD: сколько latency он добавляет к ответу (Vosk-endpoint).

Зачем: Vosk завершает фразу по ТИШИНЕ
(`KaldiRecognizer.AcceptWaveform` -> True). VAD вырезает тишину, поэтому
без «хвоста» (`vad_hangover_ms`) Vosk не видит паузу и НЕ отдаёт
финальный текст — Феникс отвечает поздно или не отвечает вовсе.

Скрипт синтезирует русскую речь (SAPI), добавляет комнатный шум и меряет,
на какой секунде Vosk отдаёт фразу в трёх режимах:
    VAD OFF        — эталон (как было до VAD)
    VAD ON h=0     — регресс: тишина не уходит в Vosk
    VAD ON h=N     — с «хвостом» (текущая настройка vad_hangover_ms)

Запуск:
    python scripts/vadbench.py
    python scripts/vadbench.py "Феникс, который час"
    python scripts/vadbench.py --wav C:\\temp\\speech.wav
"""

import argparse
import json
import os
import sys
import tempfile
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

SR = 16000
NOISE_RMS = 40      # «тихая комната» после речи


def _block_samples(sr: int = SR) -> int:
    """Размер блока аудио как в бою (Listener._block_size).

    Раньше здесь были захардкоженные 8000 (500 мс) — и бенчмарк мерил не
    то, что происходит в Фениксе, когда в stt.py блок сменили на 128 мс
    (главная ступенька задержки ответа). Теперь размер берётся оттуда же,
    откуда его берёт Listener.
    """
    from jarvis.stt import DEFAULT_BLOCK_MS, MIN_BLOCK_SAMPLES

    return max(MIN_BLOCK_SAMPLES,
               int(round(sr * DEFAULT_BLOCK_MS / 1000.0)))



def _synth_sapi(text: str, path: str) -> str:
    """Синтез русской речи через SAPI (comtypes). Возвращает имя голоса."""
    import comtypes.client

    voice = comtypes.client.CreateObject("SAPI.SpVoice")
    picked = "по умолчанию"
    try:
        for v in voice.GetVoices():
            lang = v.GetAttribute("Language")
            if lang and int(lang, 16) == 0x419:  # 0x419 = ru-RU
                voice.Voice = v
                picked = v.GetDescription()
                break
    except Exception:
        pass

    stream = comtypes.client.CreateObject("SAPI.SpFileStream")
    stream.Open(path, 3)  # SSFMCreateForWrite
    voice.AudioOutputStream = stream
    voice.Rate = 0
    voice.Speak(text)
    stream.Close()
    return picked


def _load_wav_16k(path: str):
    """WAV -> mono int16 @16 кГц (numpy)."""
    import numpy as np

    w = wave.open(path, "rb")
    sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
    data = np.frombuffer(w.readframes(n), dtype=np.int16)
    w.close()
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if sr != SR:
        idx = np.linspace(0, len(data) - 1, int(len(data) * SR / sr))
        data = np.interp(idx, np.arange(len(data)),
                         data.astype(np.float32)).astype(np.int16)
    return data


def _find_vosk_model() -> Path:
    from jarvis import paths
    from jarvis.model import MODEL_NAME

    for cand in (paths.program_models_dir() / MODEL_NAME,
                 BASE / "models" / MODEL_NAME):
        if cand.exists():
            return cand
    raise SystemExit("Не нашёл vosk-модель. Запустите jarvis (jarvis/model.py скачает).")


def _build_stream(speech):
    """[шум 2 с][речь][шум 3 с] — как реальная сессия."""
    import numpy as np

    rng = np.random.default_rng(0)
    pre = rng.normal(0, NOISE_RMS, SR * 2).astype(np.int16)
    post = rng.normal(0, NOISE_RMS, SR * 3).astype(np.int16)
    return np.concatenate([pre, speech, post]), len(pre)


def _run(model, blocks, vad, hangover_blocks, label, block_ms):
    """Гоняет блоки в Vosk и печатает, когда пришла финальная фраза."""
    from vosk import KaldiRecognizer

    from jarvis.vad import SpeechHangover

    rec = KaldiRecognizer(model, SR)
    gate = SpeechHangover(hangover_blocks) if vad is not None else None
    fed = 0
    for i, block in enumerate(blocks):
        raw = block.tobytes()
        if vad is not None:
            if not gate.feed(vad.is_speech(raw)):
                continue
        fed += 1
        if rec.AcceptWaveform(raw):
            text = json.loads(rec.Result()).get("text", "")
            print("%-14s endpoint на %4.1f с (в Vosk ушло %2d/%d блоков)  %r"
                  % (label, (i + 1) * block_ms / 1000.0, fed, len(blocks), text))
            return
    print("%-14s ФРАЗА НЕ ОТДАНА за весь поток (в Vosk ушло %2d/%d блоков) — "
          "ответа не будет!" % (label, fed, len(blocks)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Бенчмарк latency VAD + Vosk.")
    ap.add_argument("text", nargs="*", default=None,
                    help="фраза для синтеза (по умолчанию «Феникс, включи музыку»)")
    ap.add_argument("--wav", help="готовый WAV вместо синтеза")
    ap.add_argument("--hangover-ms", type=int, default=None,
                    help="хвост тишины в мс (по умолчанию из jarvis.vad)")
    args = ap.parse_args()

    from vosk import Model, SetLogLevel

    from jarvis.vad import DEFAULT_HANGOVER_MS, SpeechHangover, VAD

    SetLogLevel(-1)

    phrase = " ".join(args.text) if args.text else "Феникс, включи музыку"
    if args.wav:
        wav_path = args.wav
        print("Речь из файла:", wav_path)
    else:
        wav_path = os.path.join(tempfile.gettempdir(), "vadbench_speech.wav")
        print("Голос SAPI:", _synth_sapi(phrase, wav_path))
    print("Фраза: %r" % phrase)

    speech = _load_wav_16k(wav_path)
    stream, pre_len = _build_stream(speech)
    block_samples = _block_samples()
    blocks = [stream[i:i + block_samples]
              for i in range(0, len(stream) - block_samples + 1, block_samples)]
    speech_end = (pre_len + len(speech)) / block_samples

    hangover_ms = args.hangover_ms if args.hangover_ms is not None else DEFAULT_HANGOVER_MS
    block_ms = block_samples * 1000.0 / SR
    hangover_blocks = SpeechHangover.blocks_for_ms(hangover_ms, block_ms)

    print("Поток: %.1f с, %d блоков по %.0f мс, речь кончается на блоке %.1f"
          % (len(stream) / SR, len(blocks), block_ms, speech_end))
    print("Хвост: %d мс = %d блока(ов)\n" % (hangover_ms, hangover_blocks))

    model = Model(str(_find_vosk_model()))
    _run(model, blocks, None, 0, "VAD OFF", block_ms)
    _run(model, blocks, VAD(), 0, "VAD ON h=0", block_ms)
    _run(model, blocks, VAD(), hangover_blocks,
         "VAD ON h=%d" % hangover_blocks, block_ms)
    print("\nЖдём: VAD ON h=N не хуже VAD OFF более чем на один блок.")


if __name__ == "__main__":
    main()
