"""Build the Windows/tray phoenix icon from the project's transparent master PNG."""
from pathlib import Path
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "jarvis" / "icon.ico"
MASTER = BASE / "jarvis" / "assets" / "brand" / "phoenix-dark.png"


def draw_icon(size: int) -> Image.Image:
    # Use the same reference-matched silhouette at every size; no letter fallback.
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill="#10161e")
    with Image.open(MASTER) as source:
        mark = source.convert("RGBA")
        mark.thumbnail((max(1, int(size * .94)), max(1, int(size * .94))), Image.Resampling.LANCZOS)
        image.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return image


def main() -> int:
    image = draw_icon(256)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    draw_icon(64).save(MASTER.parent / "tray.png")
    print("Феникс: icon.ico (16–256 px), tray.png (64 px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
