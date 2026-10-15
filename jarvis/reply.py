"""Reply — результат IntentHandler.handle().

Ровно одно из двух:
    - text   — готовая строка (озвучить целиком)
    - stream — итератор строк (озвучивать по мере поступления)

Никаких «Reply ведёт себя как строка». Либо text, либо stream.
"""

from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class Reply:
    text: Optional[str] = None
    stream: Optional[Iterator[str]] = None
    allow_nonverbal: bool = False

    def __post_init__(self) -> None:
        if (self.text is None) == (self.stream is None):
            raise ValueError("Reply: ровно одно из text/stream должно быть задано")

    @property
    def is_stream(self) -> bool:
        return self.stream is not None