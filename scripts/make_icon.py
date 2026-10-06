"""Генерация иконки Феникса (jarvis/icon.ico).

Рисует синий круг с буквой «J» — тот же стиль, что в трее.
Размеры: 16, 24, 32, 48, 64, 128, 256.

Запуск:
    python scripts/make_icon.py

Результат:
    jarvis/icon.ico
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "jarvis" / "icon.ico"

# Цвета — те же, что в tray.py
BG_COLOR = (18, 32, 58, 255)       # тёмно-синий фон
ACCENT = (86, 156, 255, 255)       # акцентный синий


def draw_icon(size: int) -> Image.Image:
    """Рисует иконку заданного размера.

    Пропорции считаются от 64×64 — базовый размер.
    """
    k = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Круг
    d.ellipse(
        (2 * k, 2 * k, 62 * k, 62 * k),
        fill=BG_COLOR,
        outline=ACCENT,
        width=max(1, int(3 * k)),
    )

    # Вертикальная линия буквы «J»
    d.line(
        (38 * k, 16 * k, 38 * k, 42 * k),
        fill=ACCENT,
        width=max(1, int(6 * k)),
    )

    # Дуга буквы «J» — нижний загиб
    d.arc(
        (20 * k, 30 * k, 42 * k, 52 * k),
        start=20,
        end=180,
        fill=ACCENT,
        width=max(1, int(6 * k)),
    )

    return img


def main() -> int:
    print("Генерация иконки...")

    # Базовый размер 256×256 — качественный исходник
    base = draw_icon(256)

    # Все стандартные размеры Windows
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    base.save(OUTPUT, format="ICO", sizes=sizes)

    print(f"Готово: {OUTPUT}")
    print(f"Размеры: {', '.join(f'{w}x{h}' for w, h in sizes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())