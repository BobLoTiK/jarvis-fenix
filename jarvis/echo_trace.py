"""Explicitly opted-in, bounded local AEC trace; never uploads audio.

All file I/O and compression belong to one writer thread. Capture/render
workers only copy bounded blocks to a nonblocking queue. Missing blocks are
reported, not silently presented as continuous physical time.
"""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import queue
import threading
import time
import uuid
import wave
import zipfile

import numpy as np

log = logging.getLogger("jarvis.echo.trace")


class EchoTrace:
    rate = 16000

    def __init__(self, root, *, clock=time.monotonic, duration=90.,
                 byte_limit=32 * 1024 * 1024, queue_size=64, after_trigger=2.):
        self.clock = clock
        self.created_at = datetime.now(timezone.utc)
        self.created_monotonic = clock()
        self.duration = max(.1, min(90., float(duration)))
        self.byte_limit = max(1, min(32 * 1024 * 1024, int(byte_limit)))
        self.after_trigger = max(0., min(2., float(after_trigger)))
        name = self.created_at.strftime("aec-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        self.folder = Path(root) / name
        self.archive = self.folder.with_suffix(".zip")
        self._queue = queue.Queue(maxsize=max(1, min(64, int(queue_size))))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.done = threading.Event()
        self._started = None
        self._deadline = None
        self._bytes = self._seq = self._events = self._dropped = 0
        self._reason = "manual_close"
        self._backend_states = {}
        self._current_backend = None
        self._closed = False
        self.error = None
        self.thread = threading.Thread(target=self._run, name="aec-trace-writer", daemon=True)
        self.thread.start()
        log.warning("AEC diagnostic ARMED: local microphone recording during PCM TTS (Piper/Silero), max %.0f s; %s",
                    self.duration, self.folder)

    @property
    def active(self):
        return not self._stop.is_set() and not self.done.is_set()

    def _offer(self, kind, fields, payload=(), *, audio=False):
        # No disk operations, native calls or waiting for queue capacity here.
        with self._lock:
            if self._closed or self._stop.is_set() or self.done.is_set():
                return None
            now = self.clock()
            if self._deadline is not None and now >= self._deadline:
                self._reason = "time_limit" if self._reason == "manual_close" else self._reason
                self._stop.set()
                return None
            size = sum(len(part) for part in payload)
            if self._events >= 20000 or self._bytes + size > self.byte_limit:
                self._reason = "size_limit"
                self._stop.set()
                return None
            if audio and self._started is None:
                self._started = now
                self._deadline = min(self._deadline or now + self.duration, now + self.duration)
            self._seq += 1
            event = dict(fields, kind=kind, seq=self._seq, observed_at=now)
            # Stop timing must survive a full diagnostic queue: a lost JSON
            # event must not prolong microphone recording after a trigger.
            if kind == "decision" and fields.get("triggered"):
                self._deadline = min(self._deadline or now + self.duration,
                                     now + self.after_trigger)
                self._reason = "after_first_trigger"
            try:
                self._queue.put_nowait((event, payload))
            except queue.Full:
                self._dropped += 1
                return None
            self._events += 1
            self._bytes += size
            return self._seq

    def backend(self, name, voice=None, *, reference_available):
        state = {"backend": str(name)[:32],
                 "voice": str(voice)[:128] if voice is not None else None,
                 "reference_available": bool(reference_available)}
        with self._lock:
            if self._closed or self._stop.is_set() or state == self._current_backend:
                return False
            self._current_backend = state
            if len(self._backend_states) < 16 or state["backend"] in self._backend_states:
                self._backend_states[state["backend"]] = state
        self.note("backend", **state)
        return True

    def render(self, audio, rate, when, serial, *, backend="unknown"):
        if not self.active:
            return None
        pcm = np.asarray(audio, dtype="<f4").tobytes()
        return self._offer("render", {"when": when, "rate": rate, "serial": serial,
                                       "samples": len(audio), "backend": backend},
                           (pcm,), audio=True)

    def capture(self, raw, reference, cleaned, when, **fields):
        if not self.active:
            return None
        # Explicit little endian representation, independent of host byte order.
        far = np.asarray(reference, dtype="<i2").tobytes()
        return self._offer("capture", dict(fields, when=when, samples=len(raw) // 2),
                           (bytes(raw), far, bytes(cleaned)), audio=True)

    def note(self, kind, **fields):
        return self._offer(kind, fields)

    def close(self):
        with self._lock:
            self._closed = True
            self._stop.set()
        # Never join an I/O thread from a real-time capture/render path.
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=5.)

    def _run(self):
        frames = render_bytes = 0
        wavs = []
        events = render = None
        try:
            self.folder.mkdir(parents=True, exist_ok=False)
            for name in ("microphone", "reference", "cleaned"):
                stream = wave.open(str(self.folder / (name + ".wav")), "wb")
                stream.setparams((1, 2, self.rate, 0, "NONE", "not compressed"))
                wavs.append(stream)
            events = (self.folder / "events.jsonl").open("w", encoding="utf-8")
            render = (self.folder / "render.f32").open("wb")
            while True:
                with self._lock:
                    if self._deadline is not None and self.clock() >= self._deadline:
                        if self._reason == "manual_close":
                            self._reason = "time_limit"
                        self._stop.set()
                try:
                    event, payload = self._queue.get(timeout=.05)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue
                if event["kind"] == "capture":
                    if not (len(payload[0]) == len(payload[1]) == len(payload[2])):
                        raise ValueError("Diagnostic channel lengths differ")
                    event["frame_offset"] = frames
                    for stream, data in zip(wavs, payload):
                        stream.writeframesraw(data)
                    frames += event["samples"]
                elif event["kind"] == "render":
                    event["byte_offset"] = render_bytes
                    render.write(payload[0])
                    render_bytes += len(payload[0])
                events.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        except Exception as exc:
            self.error = str(exc)
            self._stop.set()
            log.warning("AEC diagnostic failed; audio processing continues: %s", exc)
        finally:
            for stream in wavs:
                try:
                    stream.close()
                except Exception:
                    pass
            for stream in (events, render):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            # Block late producers before taking final counts or creating ZIP.
            with self._lock:
                self._closed = True
                summary = {
                    "format_version": 2, "sample_rate": self.rate,
                    "backends": list(self._backend_states.values()),
                    "trace_status": ("pcm_trace" if frames else
                                     "render_only_no_capture" if render_bytes else
                                     "metadata_only_no_pcm"),
                    "clock_anchor_utc": self.created_at.isoformat(),
                    "clock_anchor_local": self.created_at.astimezone().isoformat(),
                    "clock_anchor_monotonic": self.created_monotonic,
                    "channels": ["microphone.wav", "reference.wav", "cleaned.wav"],
                    "capture_frames": frames, "render_bytes": render_bytes,
                    "queued_events": self._events, "dropped_events": self._dropped,
                    "audio_bytes_reserved": self._bytes, "byte_limit": self.byte_limit,
                    "duration_limit_seconds": self.duration,
                    "stop_reason": self._reason, "error": self.error,
                    "privacy": "Local only; includes microphone audio; no upload.",
                    "alignment": "WAV channels share frame offsets. Use capture.when for gaps; "
                                 "do not treat appended blocks as a continuous wall clock.",
                    "render_format": "Little-endian float32 mono. Each render event gives "
                                     "byte_offset, samples, rate, estimated playback when and serial. "
                                     "render_end events trim cancelled writes at when.",
                    "timestamps": "Monotonic seconds; playback/capture timestamps are estimates, "
                                  "not hardware loopback measurements.",
                }
            try:
                if self.folder.exists():
                    (self.folder / "summary.json").write_text(
                        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                    if self.error is None:
                        pending = self.archive.with_suffix(".zip.partial")
                        with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED,
                                             compresslevel=1) as archive:
                            for file in sorted(self.folder.iterdir()):
                                archive.write(file, file.name)
                        pending.replace(self.archive)
                        log.warning("AEC diagnostic SAVED: %s (stop=%s, dropped=%d); recording OFF",
                                    self.archive, self._reason, self._dropped)
            except Exception as exc:
                self.error = str(exc)
                log.warning("AEC diagnostic finalization failed: %s; files: %s", exc, self.folder)
            finally:
                self.done.set()
