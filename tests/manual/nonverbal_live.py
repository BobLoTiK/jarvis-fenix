"""Manual sample audition; optional --mix <speech.wav>. Opens the audio output device."""

import argparse
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    from jarvis import paths
    from jarvis.audio_output import decode_wav, encode_wav, play_wav
    from jarvis.nonverbal import Reaction, SAMPLES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=sorted(SAMPLES), default="hmm")
    parser.add_argument(
        "--mix",
        type=Path,
        help="Recorded or synthesized speech WAV, not a live microphone",
    )
    args = parser.parse_args()
    sample = paths.nonverbal_dir() / SAMPLES[args.kind]
    token = threading.Event()
    if args.mix:
        play_wav(args.mix.read_bytes(), token, Reaction(sample, -15))
    else:
        audio, rate = decode_wav(sample.read_bytes())
        play_wav(encode_wav(audio * 10 ** (-15 / 20), rate), token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
