"""Opt-in Piper AEC prototype. No devices, drivers or downloads.
Audio files are created only with explicit FENIX_AEC_DIAGNOSTICS=1.

One capture worker owns the native processor. The PortAudio callback only
queues bounded PCM; render writes publish a bounded timestamped reference.
Render timestamps are estimates, not a measured DAC/microphone clock sync.
"""
from collections import deque
import logging
import math
import os
import queue
import threading
import time

import numpy as np

log = logging.getLogger("jarvis.echo")


def make_echo_path(config):
    if not config.get("aec_enabled", False):
        return None
    rate = config.get("sample_rate", 16000)
    if rate != 16000:
        log.warning("AEC: прототип только для микрофона 16000 Гц; остаётся прежний тракт")
        return None
    try:
        delay = float(config.get("aec_stream_delay_ms", 40))
        if not math.isfinite(delay):
            raise ValueError("nonfinite delay")
        delay = int(min(500, max(0, delay)))
    except (TypeError, ValueError, OverflowError):
        delay = 40
    trace = None
    if os.environ.get("FENIX_AEC_DIAGNOSTICS") == "1":
        try:
            from jarvis.echo_trace import EchoTrace
            from jarvis.paths import user_dir
            trace = EchoTrace(user_dir() / "logs" / "aec_diagnostics")
        except Exception:
            log.warning("AEC diagnostic unavailable; audio processing continues", exc_info=True)
    return EchoPath(delay_ms=delay, trace=trace)


class RenderTap:
    def __init__(self, owner, serial):
        self.owner, self.serial = owner, serial

    def feed(self, samples, rate, when):
        self.owner._publish(self.serial, samples, rate, when)

    def finish(self, when):
        self.owner._finish_render(self.serial, when)


class EchoPath:
    """Single native owner, max 4 capture blocks and 2 seconds of reference."""
    rate = 16000

    def __init__(self, delay_ms=40, *, factory=None, clock=time.monotonic, trace=None):
        self.delay_ms, self._factory, self.clock = delay_ms, factory, clock
        self._trace = trace
        self._backend_name = "unknown"
        self._lock = threading.RLock()
        self._delivery_lock = threading.RLock()
        self._queue = queue.Queue(maxsize=4)
        self._references = deque(maxlen=80)
        self._epoch = 0
        self._reset = False
        self._gap = False
        self._serial = 0
        self._rendering = False
        self._tail_until = float("-inf")
        self._render_blocks = 0
        self._good_cancellation_blocks = 0
        self._barge_verified = False
        self._last_attenuation = None
        self._best_attenuation = None
        self._last_similarity = None
        self._last_raw_similarity = None
        self._path_change_blocks = 0
        self._readaptations = 0
        self._healthy = False
        self._closed = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self._deliver = None
        self.state = "not_started"
        self.dropped = self.processed = 0

    @property
    def diagnostic_mode(self):
        # Stable for this process, including after the trace time limit.
        return self._trace is not None

    def set_trace_backend(self, name, voice=None):
        if self._trace is None:
            return
        name = str(name)[:32]
        with self._lock:
            self._backend_name = name
        supported = name in ("piper", "silero")
        changed = self._trace.backend(name, voice, reference_available=supported)
        if changed:
            if supported:
                log.warning("AEC diagnostic backend=%s: common PCM reference; "
                            "AEC active in this diagnostic session", name)
            else:
                log.warning("AEC diagnostic backend=%s: NO PCM REFERENCE; full AEC "
                            "recording unavailable, no fake reference is recorded. "
                            "Close normally to save metadata; loopback capture is required.", name)

    def start(self, deliver):
        if self.thread is not None or self._closed.is_set():
            return
        self._deliver = deliver
        self.state = "starting"
        self.thread = threading.Thread(target=self._run, daemon=True, name="aec-capture")
        self.thread.start()

    def begin_render(self):
        with self._lock:
            if self._closed.is_set():
                return None
            self._serial += 1
            self._rendering = True
            self._render_blocks = 0
            self._good_cancellation_blocks = 0
            self._barge_verified = False
            self._last_attenuation = None
            self._best_attenuation = None
            self._last_similarity = None
            self._last_raw_similarity = None
            self._path_change_blocks = 0
            self._trace_note("render_begin", serial=self._serial, backend=self._backend_name)
            return RenderTap(self, self._serial)

    def _publish(self, serial, samples, rate, when):
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        if (audio.ndim != 1 or not len(audio) or not 8000 <= rate <= 192000
                or len(audio) > rate // 4 or not math.isfinite(when)
                or not np.isfinite(audio).all()):
            raise ValueError("Invalid/oversized render reference")
        audio = np.clip(audio, -1, 1).copy()
        with self._lock:
            if serial != self._serial or self._closed.is_set():
                return
            self._references.append((when, int(rate), audio))
            cutoff = self.clock() - 2.0
            while self._references and self._references[0][0] < cutoff:
                self._references.popleft()
        if self._trace is not None:
            self._trace.render(audio, int(rate), when, serial, backend=self._backend_name)

    def _finish_render(self, serial, when):
        with self._lock:
            if serial != self._serial:
                return
            self._rendering = False
            self._tail_until = when + .4
            # A cancelled/failed write must not leave future samples scheduled.
            kept = deque(maxlen=80)
            for start, rate, audio in self._references:
                n = min(len(audio), max(0, int(round((when - start) * rate))))
                if n:
                    kept.append((start, rate, audio[:n]))
            self._references = kept
            blocks = self._render_blocks
            verified = self._barge_verified
            attenuation = self._last_attenuation
            similarity = self._last_similarity
        self._trace_note("render_end", serial=serial, when=when)
        log.info(
            "AEC render: state=%s, blocks=%d, barge=%s, attenuation=%s, similarity=%s",
            self.state,
            blocks,
            "ready" if verified else "guarded",
            "-" if attenuation is None else f"{attenuation:.2f}",
            "-" if similarity is None else f"{similarity:.2f}",
        )

    def suspend_render(self):
        self._trace_note("render_suspend", when=self.clock())
        with self._lock:
            self._serial += 1
            self._rendering = False
            self._tail_until = float("-inf")
            self._references.clear()
            self._reset = True
            self._barge_verified = False

    def _trace_note(self, kind, **fields):
        trace = self._trace
        if trace is not None:
            trace.note(kind, **fields)

    def record_trace_decision(self, trace_id, **fields):
        self._trace_note("decision", capture_id=trace_id, **fields)

    def render_guard_active(self):
        """True while Piper can be audible, even when native AEC is unavailable.

        This is deliberately independent from ``_healthy``.  Falling back to
        legacy RMS barge-in while Piper is playing is exactly the unsafe case:
        the assistant's own first syllable can stop the reply.
        """
        with self._lock:
            return self._rendering or self.clock() <= self._tail_until

    def diagnostics(self):
        """Small audio-free status snapshot for logs and future UI wiring."""
        with self._lock:
            return {
                "state": self.state,
                "render_blocks": self._render_blocks,
                "barge_verified": self._barge_verified,
                "attenuation": self._last_attenuation,
                "best_attenuation": self._best_attenuation,
                "similarity": self._last_similarity,
                "raw_similarity": self._last_raw_similarity,
                "readaptations": self._readaptations,
            }

    def _reference(self, when, count):
        with self._lock:
            if not self._rendering and when > self._tail_until:
                return None
            refs = tuple(self._references)
        # Map the played mono reference to the capture clock and rate. Native
        # AEC handles the residual delay; this is NOT a loopback measurement.
        far, _ = self._render_window(refs, when, count)
        return np.round(far * 32767).astype(np.int16)

    def _render_window(self, refs, when, count):
        """Rasterize timestamped chunks without floating-point boundary holes."""
        far = np.zeros(count, dtype=np.float64)
        covered = np.zeros(count, dtype=bool)
        offsets = np.arange(count, dtype=np.float64) / self.rate
        for start, rate, audio in refs:
            positions = ((when - start) + offsets) * rate
            # Clock arithmetic at a chunk boundary can be off by ~1e-8
            # samples. A tolerance far below one sample assigns that point
            # to the next chunk rather than leaving a fabricated silence.
            mask = (positions >= -1e-6) & (positions < len(audio) - 1e-6)
            if mask.any():
                far[mask] = np.interp(positions[mask], np.arange(len(audio)), audio)
                covered[mask] = True
        return far, covered

    def _echo_similarities(self, signals, when):
        """Normalized cross-correlation at EVERY sample lag (-100..500 ms).

        A 20 ms grid is unsuitable for waveform correlation: even the correct
        acoustic delay can fall between grid points and look uncorrelated.
        Resample the bounded render history once, then use FFT convolution and
        sliding centered energies. Only fully covered reference windows count;
        missing/future reference must not become a zero-padded false match.
        This is an echo-presence measurement, not speaker identification.
        """
        with self._lock:
            refs = tuple(self._references)
        if not signals:
            return ()
        count = len(signals[0])
        if not refs or not count:
            return tuple(None for _ in signals)
        if any(len(signal) != count for signal in signals):
            raise ValueError("Correlation signals must have equal lengths")
        lag_span = int(round(.6 * self.rate))
        far, covered = self._render_window(refs, when - .5, count + lag_span)

        def window_sum(values):
            sums = np.concatenate(([0.], np.cumsum(values, dtype=np.float64)))
            return sums[count:] - sums[:-count]

        squared = window_sum(far * far)
        energy = np.maximum(0., squared - window_sum(far) ** 2 / count)
        # Centered constant windows have zero energy; cumsum roundoff must
        # not turn them into a valid waveform observation.
        usable = ((window_sum(covered) == count)
                  & (energy > np.maximum(1e-12, squared * 1e-10)))
        if not usable.any():
            return tuple(None for _ in signals)
        fft_size = 1 << (len(far) + count - 2).bit_length()
        far_fft = np.fft.rfft(far, n=fft_size)
        scores = []
        for signal in signals:
            near = np.array(signal, dtype=np.float64, copy=True)
            near -= near.mean()
            near_energy = float(np.dot(near, near))
            if near_energy < 1:
                scores.append(0.0)
                continue
            convolution = np.fft.irfft(
                far_fft * np.fft.rfft(near[::-1], n=fft_size), n=fft_size
            )
            dots = convolution[count - 1:len(far)]
            normalized = np.abs(dots[usable]) / np.sqrt(near_energy * energy[usable])
            scores.append(float(np.clip(normalized.max(), 0., 1.)))
        return tuple(scores)

    def _echo_similarity(self, cleaned, when):
        return self._echo_similarities((cleaned,), when)[0]

    def submit(self, pcm, when):
        if not self._healthy or self._closed.is_set():
            return False  # normal listener path, including missing native DLL
        if len(pcm) % 2 or len(pcm) > self.rate // 2 or not math.isfinite(when):
            return False
        item = (self._epoch, bytes(pcm), when, self.clock())
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Never substitute unfiltered audio out of order on overload.
            self.dropped += 1
            self.discontinuity()
        return True

    def take_gap(self):
        with self._lock:
            value, self._gap = self._gap, False
            return value

    def discontinuity(self):
        # PortAudio callback: no waiting on VAD/delivery/native processing.
        with self._lock:
            self._epoch += 1
            self._gap = self._reset = True

    def flush(self, *, reset=False):
        # No native calls here. In-flight output is invalidated before the
        # listener drains its ASR queue; late pre-flush PCM cannot return.
        with self._delivery_lock:
            self._epoch += 1
            self._gap = True
            if reset:
                self.suspend_render()
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

    def close(self):
        self._closed.set()
        self.flush(reset=True)
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=.5)
        if self._trace is not None:
            self._trace.close()

    def _create_processor(self):
        if self._factory is not None:
            return self._factory()
        from pywebrtc_audio import AudioProcessor
        return AudioProcessor(sample_rate=self.rate, num_channels=1,
                              echo_cancellation=True, noise_suppression=False,
                              auto_gain_control=False, stream_delay_ms=self.delay_ms)

    def _run(self):
        try:
            processor = self._create_processor()
            if self._closed.is_set():
                return
            self._healthy = True
            self.state = "ready"
            log.info("AEC: %s, WebRTC AEC3 готов; delay hint=%d мс. Windows-приёмка требуется",
                     "diagnostic common PCM (Piper/Silero)" if self.diagnostic_mode else "Piper PCM",
                     self.delay_ms)
        except Exception:
            self.state = "unavailable"
            log.warning("AEC недоступен; остаётся прежний тракт. Установи optional-пакет через install_aec.bat", exc_info=True)
            return
        finally:
            self.ready.set()
        try:
            while not self._closed.is_set():
                try:
                    epoch, raw, when, queued_at = self._queue.get(timeout=.1)
                except queue.Empty:
                    continue
                if epoch != self._epoch or self.clock() - queued_at > .3:
                    self.dropped += 1
                    with self._lock:
                        self._gap = self._reset = True
                    continue
                with self._lock:
                    reset, self._reset = self._reset, False
                if reset:
                    self._trace_note("native_reset", reason="discontinuity", when=when,
                                     epoch=epoch, phase="before_current_block")
                    processor.reset()
                far = self._reference(when, len(raw) // 2)
                probability = None
                if far is None:
                    cleaned = raw  # unsupported backend / idle: original behavior
                else:
                    near = np.frombuffer(raw, dtype=np.int16).copy()
                    result = np.asarray(processor.process(near, far))
                    if result.shape != near.shape or result.dtype != np.int16:
                        raise ValueError("AEC returned invalid PCM")
                    cleaned = result.tobytes()
                    p = float(processor.speech_probability)
                    probability = p if math.isfinite(p) and 0 <= p <= 1 else 0.0
                    raw_rms = float(np.sqrt(np.mean(near.astype(np.float64) ** 2)))
                    clean_rms = float(np.sqrt(np.mean(result.astype(np.float64) ** 2)))
                    far_rms = float(np.sqrt(np.mean(far.astype(np.float64) ** 2)))
                    similarity, raw_similarity = self._echo_similarities(
                        (result, near), when
                    )
                    with self._lock:
                        self._render_blocks += 1
                        # This ratio belongs to THIS capture block. Quiet blocks
                        # must never inherit a previous phoneme's attenuation.
                        self._last_attenuation = (
                            clean_rms / raw_rms if raw_rms >= 1.0 else None
                        )
                        # Fail closed: barge-in becomes available only after the
                        # current render has demonstrated actual cancellation.
                        if far_rms >= 150 and raw_rms >= 150:
                            if clean_rms <= raw_rms * .65:
                                self._good_cancellation_blocks += 1
                                if (self._best_attenuation is None
                                        or self._last_attenuation < self._best_attenuation):
                                    self._best_attenuation = self._last_attenuation
                            else:
                                self._good_cancellation_blocks = 0
                            if self._good_cancellation_blocks >= 2:
                                self._barge_verified = True
                        self._last_similarity = similarity
                        self._last_raw_similarity = raw_similarity
                        # Moving a microphone towards a speaker changes the
                        # acoustic impulse response abruptly.  Do not keep a
                        # previously latched "verified" state through that
                        # change: two strongly render-correlated degraded
                        # blocks force a native re-adaptation window.
                        path_changed = bool(
                            self._barge_verified
                            and self._last_attenuation is not None
                            and self._last_attenuation >= max(
                                .30, (self._best_attenuation or .05) * 5
                            )
                            and clean_rms >= 60
                            and raw_similarity is not None
                            and raw_similarity >= .45
                            and similarity is not None
                            and similarity >= .22
                        )
                        if path_changed:
                            self._path_change_blocks += 1
                        else:
                            self._path_change_blocks = max(
                                0, self._path_change_blocks - 1
                            )
                        if self._path_change_blocks >= 2:
                            self._barge_verified = False
                            self._good_cancellation_blocks = 0
                            self._best_attenuation = None
                            self._path_change_blocks = 0
                            self._readaptations += 1
                            self._trace_note("native_reset", reason="acoustic_path_change",
                                             when=when, epoch=epoch,
                                             readaptations=self._readaptations,
                                             phase="after_current_block")
                            processor.reset()
                            log.info(
                                "AEC: акустический путь изменился; "
                                "barge-in временно защищён до переадаптации"
                            )
                        verified = self._barge_verified
                    self.processed += 1
                with self._delivery_lock:
                    if epoch == self._epoch and not self._closed.is_set():
                        gap = self.take_gap()
                        if epoch != self._epoch:
                            self._gap = True
                            continue
                        trace_id = None
                        if self._trace is not None and far is not None:
                            trace_id = self._trace.capture(
                                raw, far, cleaned, when, epoch=epoch, gap=gap,
                                capture_queue_dropped=self.dropped,
                                backend=self._backend_name, render_serial=self._serial,
                                probability=probability, **self.diagnostics()
                            )
                        self._deliver(
                            cleaned,
                            aec_probability=probability,
                            aec_echo_similarity=similarity if far is not None else None,
                            aec_raw_similarity=raw_similarity if far is not None else None,
                            aec_verified=verified if far is not None else False,
                            aec_attenuation=self._last_attenuation if far is not None else None,
                            aec_best_attenuation=self._best_attenuation if far is not None else None,
                            source_pcm=raw,
                            aec_reset=gap,
                            **({"aec_trace_id": trace_id} if trace_id is not None else {}),
                        )
        except Exception:
            self.state = "failed"
            log.warning("AEC: обработка остановлена; следующий микрофонный блок идёт прежним путём", exc_info=True)
        finally:
            self._healthy = False
            self.flush(reset=True)
            if self._closed.is_set():
                self.state = "closed"
