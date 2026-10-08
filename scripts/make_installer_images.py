"""Генерация картинок для Inno Setup установщика Феникса.

Создаёт два BMP:
    installer_banner.bmp  — 164×314, вертикальный баннер слева
    installer_small.bmp   — 55×55, иконка вверху справа

Оба — из jarvis/icon.ico.

Запуск:
    python scripts/make_installer_images.py
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent.parent
ICON_PATH = BASE / "jarvis" / "icon.ico"
BANNER_OUT = BASE / "installer_banner.bmp"
SMALL_OUT = BASE / "installer_small.bmp"

BG_COLOR = (18, 32, 58)
ACCENT = (86, 156, 255)
TEXT_COLOR = (230, 237, 243)
BMP_FORMAT = "BMP"


def _find_font(size: int):
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _load_icon(size: int) -> Image.Image:
    if not ICON_PATH.exists():
        print(f"ОШИБКА: {ICON_PATH} не найден.")
        sys.exit(1)
    img = Image.open(ICON_PATH).convert("RGBA")
    return img.resize((size, size), Image.LANCZOS)


def make_banner() -> None:
    w, h = 164, 314
    img = Image.new("RGB", (w, h), BG_COLOR)
    d = ImageDraw.Draw(img)

    for y in range(h):
        k = y / h
        r = int(BG_COLOR[0] + (0 - BG_COLOR[0]) * k * 0.35)
        g = int(BG_COLOR[1] + (0 - BG_COLOR[1]) * k * 0.35)
        b = int(BG_COLOR[2] + (10 - BG_COLOR[2]) * k * 0.35)
        d.line([(0, y), (w, y)], fill=(r, g, b))

    d.rectangle([(0, 0), (w, 4)], fill=ACCENT)

    icon = _load_icon(96)
    img.paste(icon, ((w - 96) // 2, 50), icon)

    font_title = _find_font(26)
    text = "Феникс"
    bbox = d.textbbox((0, 0), text, font=font_title)
    tw = bbox[2] - bbox[0]
    d.text(((w - tw) // 2, 170), text, fill=TEXT_COLOR, font=font_title)

    font_sub = _find_font(11)
    sub = "Голосовой ассистент"
    bbox = d.textbbox((0, 0), sub, font=font_sub)
    tw = bbox[2] - bbox[0]
    d.text(((w - tw) // 2, 205), sub, fill=ACCENT, font=font_sub)

    try:
        sys.path.insert(0, str(BASE))
        from jarvis import __version__
        ver_text = f"v{__version__}"
    except Exception:
        ver_text = "v1.0.0"

    font_ver = _find_font(10)
    bbox = d.textbbox((0, 0), ver_text, font=font_ver)
    tw = bbox[2] - bbox[0]
    d.text(((w - tw) // 2, h - 25), ver_text, fill=(139, 148, 158), font=font_ver)

    img.save(BANNER_OUT, format=BMP_FORMAT)
    print(f"OK: {BANNER_OUT.name} ({w}x{h})")


def make_small() -> None:
    size = 55
    icon = _load_icon(size)
    bg = Image.new("RGB", (size, size), BG_COLOR)
    bg.paste(icon, (0, 0), icon)
    bg.save(SMALL_OUT, format=BMP_FORMAT)
    print(f"OK: {SMALL_OUT.name} ({size}x{size})")


def main() -> int:
    print("Генерация картинок для Inno Setup...")
    print(f"Источник: {ICON_PATH.name}")
    print()
    make_banner()
    make_small()
    print()
    print("Готово. Теперь используй в installer.iss:")
    print("  WizardImageFile=installer_banner.bmp")
    print("  WizardSmallImageFile=installer_small.bmp")
    return 0


if __name__ == "__main__":
    sys.exit(main())