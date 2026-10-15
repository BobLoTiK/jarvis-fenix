"""Shared cancellable PCM output for Speaker and the three WAV-based TTS engines."""

import io
import logging
import time
import wave

log = logging.getLogger("jarvis.tts")


def decode_wav(data):
    import numpy as np

    with wave.open(io.BytesIO(data), "rb") as wf:
        channels, width, rate, frames, compression, _ = wf.getparams()
        if compression != "NONE" or width not in (1, 2, 3, 4) or not 1 <= channels <= 2:
            raise ValueError("Unsupported PCM format")
        if not 8000 <= rate <= 192000 or frames / rate > 600:
            raise ValueError("Invalid WAV duration or sample rate")
        raw = wf.readframes(frames)
    if len(raw) != frames * channels * width:
        raise ValueError("Truncated PCM data")
    if width == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        x = b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16
        audio = ((x ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
    else:
        audio = np.frombuffer(raw, dtype="<i2" if width == 2 else "<i4").astype(
            np.float32
        )
        audio /= float(2 ** (width * 8 - 1))
    return audio.reshape(-1, channels), rate


def mix_reaction(audio, rate, reaction):
    """Mix relative to speech RMS, resampling the short sample; never amplify speech."""
    import numpy as np

    if reaction is None or not len(audio):
        return audio
    try:
        sample, sample_rate = decode_wav(reaction.path.read_bytes())
        if not len(sample) or len(sample) / sample_rate > 3.0:
            return audio
        sample = sample.mean(axis=1)
        count = max(1, round(len(sample) * rate / sample_rate))
        sample = np.interp(
            np.arange(count) * sample_rate / rate, np.arange(len(sample)), sample
        ).astype(np.float32)
        active = audio[np.abs(audio) > 0.001]
        speech_rms = float(np.sqrt(np.mean(active**2))) if len(active) else 0
        sample_rms = float(np.sqrt(np.mean(sample**2)))
        if speech_rms <= 0 or sample_rms <= 0:
            return audio
        sample *= speech_rms / sample_rms * 10 ** (reaction.gain_db / 20)
        mixed = np.zeros(
            (max(len(audio), len(sample)), audio.shape[1]), dtype=np.float32
        )
        mixed[: len(audio)] = audio
        mixed[: len(sample)] += sample[:, None]
        peak = float(np.max(np.abs(mixed)))
        if peak > 0.98:
            mixed *= 0.98 / peak
        return mixed
    except (OSError, ValueError, wave.Error, EOFError):
        log.warning(
            "Non-verbal: повреждён или недоступен сэмпл, оставляю речь без реакции"
        )
        return audio


def encode_wav(audio, rate):
    import numpy as np

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(audio.shape[1])
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def play_wav(wav_bytes, token, reaction=None):
    if token.is_set() or not wav_bytes:
        return
    audio, rate = decode_wav(wav_bytes)
    audio = mix_reaction(audio, rate, reaction)
    if token.is_set() or not len(audio):
        return
    played = False
    try:
        import sounddevice as sd

        chunk = max(1, round(rate * 0.05))
        with sd.OutputStream(
            samplerate=rate, channels=audio.shape[1], dtype="float32"
        ) as stream:
            for i in range(0, len(audio), chunk):
                if token.is_set():
                    break
                # If write fails after consuming some samples, don't replay from the beginning.
                played = True
                stream.write(audio[i : i + chunk])
    except (ImportError, OSError):
        if token.is_set():
            return
        if played:
            raise
        _play_windows(audio, rate, token)


def _play_windows(audio, rate, token):
    """Windows fallback only before any PCM was written; shares cancellation token."""
    from jarvis import paths
    import winsound

    if token.is_set():
        return
    with paths.temporary_audio_file() as path:
        path.write_bytes(encode_wav(audio, rate))
        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
        try:
            end = time.monotonic() + len(audio) / rate
            while time.monotonic() < end and not token.wait(0.05):
                pass
        finally:
            winsound.PlaySound(None, 0)
