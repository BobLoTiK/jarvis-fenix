"""Optional, bounded reaction policy. No LLM tags, text rewriting or extra audio thread."""

from dataclasses import dataclass
import math
from pathlib import Path
import random
import threading
import time
from weakref import WeakKeyDictionary

from jarvis import paths


SAMPLES = {
    "laugh": "laugh.wav",
    "sigh": "sigh.wav",
    "hmm": "hmm.wav",
    "yawn": "yawn.wav",
}
# No negative reaction to annoyance, no pretend illness/cough from an emotion.
REACTIONS = {
    "happy": ("laugh",),
    "excited": ("laugh",),
    "neutral": ("hmm",),
    "bored": ("hmm",),
    "tired": ("sigh", "yawn"),
}


def setting(config, key, default, lower, upper):
    try:
        value = float(config.get(key, default))
        return min(upper, max(lower, value)) if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Reaction:
    path: Path
    gain_db: float


class Nonverbal:
    """One attempt per reply token; cooldown shared across sentences and replies."""

    def __init__(self, config, *, clock=time.monotonic, rng=None, mood_getter=None):
        self.config = config
        self.clock = clock
        self.rng = rng or random.Random()
        self.mood_getter = mood_getter
        self._lock = threading.RLock()
        self._sessions = WeakKeyDictionary()
        self._last_at = float("-inf")

    def begin(self, token, allowed=False):
        with self._lock:
            self._sessions[token] = bool(allowed)

    def take(self, token):
        with self._lock:
            allowed = self._sessions.pop(token, False)
            if (
                not allowed
                or token.is_set()
                or not self.config.get("nonverbal_enabled", False)
            ):
                return None
            now = self.clock()
            cooldown = setting(
                self.config, "nonverbal_cooldown_sec", 45.0, 10.0, 3600.0
            )
            if now - self._last_at < cooldown:
                return None
            chance = setting(self.config, "nonverbal_probability", 0.2, 0.0, 1.0)
            if self.rng.random() >= chance:
                return None
            if self.mood_getter is None:
                from jarvis import mood

                state = mood.get_state()  # includes the existing prosody → mood policy
            else:
                state = self.mood_getter()
            choices = REACTIONS.get(state, ())
            if not choices:
                return None
            path = paths.nonverbal_dir() / SAMPLES[self.rng.choice(choices)]
            if not path.is_file():
                return None
            self._last_at = now
            return Reaction(
                path, setting(self.config, "nonverbal_gain_db", -15.0, -18.0, -12.0)
            )
