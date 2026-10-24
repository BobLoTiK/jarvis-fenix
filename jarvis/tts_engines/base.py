"""Базовый класс TTS-движка.

Все движки (Piper, Silero, SAPI) реализуют этот интерфейс.
Speaker работает только через него — не знает о конкретных библиотеках.
"""

from abc import ABC, abstractmethod
from typing import Iterator


class BaseEngine(ABC):
    """Один TTS-движок."""

    #: Имя движка (для логов и config: "piper", "silero", ...)
    name: str = "base"

    #: Доступные голоса {key: human_description}
    voices: dict = {}

    #: Качество по умолчанию ("medium" / "high")
    default_quality: str = "medium"

    #: Скорость по умолчанию
    default_rate: float = 1.15

    @abstractmethod
    def is_available(self) -> bool:
        """Движок готов к работе?"""
        ...

    @abstractmethod
    def synthesize(self, text: str, voice: str, rate: float) -> bytes:
        """Синтез текста → WAV-байты (PCM 16-bit).

        text — уже подготовленный (prepare_text)
        voice — ключ из self.voices
        rate — множитель скорости (1.0 = норма)
        Возвращает полный WAV-файл в bytes.
        """
        ...

    @abstractmethod
    def speak_stream(self, text_iter: Iterator[str], voice: str,
                     rate: float, token) -> str:
        """Стриминг: озвучивает по мере поступления текста.

        token — threading.Event для прерывания (barge-in).
        Возвращает полный озвученный текст.
        """
        ...

    def set_wav_player(self, player) -> None:
        """Speaker supplies one output/mixing path for normal and streamed speech."""
        self._wav_player = player

    def _output_wav(self, wav_bytes, token) -> None:
        player = getattr(self, "_wav_player", None)
        if player is None:
            from jarvis.audio_output import play_wav
            player = play_wav
        player(wav_bytes, token)

    def set_voice(self, voice: str) -> None:
        """Сменить голос (переопределяется, если движок поддерживает)."""
        pass

    def set_rate(self, rate: float) -> None:
        """Сменить скорость речи."""
        pass

    def stop(self) -> None:
        """Прервать текущее воспроизведение (опционально)."""
        pass