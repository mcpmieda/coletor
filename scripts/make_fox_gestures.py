"""Draw the fox's extra tray gestures from fox-idle.ico, at every icon size.

fox-ear / fox-ear-right / fox-ears: the left, right or both ears droop and tip outwards.
fox-bob: the head dips by about 6% (a breath), so even a 16 px icon moves.
Pixel art stays hard-edged (nearest-neighbour). Run from the repository root:
    python scripts/make_fox_gestures.py
"""
from pathlib import Path

from PIL import Image, ImageOps

FOLDER = Path(__file__).resolve().parents[1] / "app/assets/fox-icons"
SIZES = [16, 20, 24, 32, 48, 64, 256]


def frame(size):
    image = Image.open(FOLDER / "fox-idle.ico")
    image.size = (size, size)
    return image.convert("RGBA")


def flop_left_ear(image):
    """Lower the left ear and tip it outwards by whole pixels (clean at 16 px)."""
    size = image.width
    cut = round(size * 0.40)
    down = max(1, round(size * 0.09))
    out = max(1, round(size * 0.05))
    ear = Image.new("RGBA", image.size, (0, 0, 0, 0))
    base = image.copy()
    for y in range(cut):
        for x in range(size // 2):
            pixel = image.getpixel((x, y))
            if pixel[3]:
                ear.putpixel((x, y), pixel)
                base.putpixel((x, y), (0, 0, 0, 0))
    # The ear's base stays under the moved ear, so the head keeps its outline.
    for y in range(max(0, cut - down), cut):
        for x in range(size // 2):
            if image.getpixel((x, y))[3]:
                base.putpixel((x, y), image.getpixel((x, y)))
    moved = Image.new("RGBA", image.size, (0, 0, 0, 0))
    moved.alpha_composite(ear, (-out, down))
    moved.alpha_composite(base)
    base.alpha_composite(moved)
    return moved


def flop_right_ear(image):
    return ImageOps.mirror(flop_left_ear(ImageOps.mirror(image)))


def bob(image):
    size = image.width
    shift = max(1, round(size * 0.06))
    moved = Image.new("RGBA", image.size, (0, 0, 0, 0))
    moved.alpha_composite(image.crop((0, 0, size, size - shift)), (0, shift))
    return moved


GESTURES = {
    "fox-ear": flop_left_ear,
    "fox-ear-right": flop_right_ear,
    "fox-ears": lambda image: flop_right_ear(flop_left_ear(image)),
    "fox-bob": bob,
}


def main():
    for name, make in GESTURES.items():
        frames = [make(frame(size)) for size in SIZES]
        frames[-1].save(FOLDER / f"{name}.ico", format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
        print("wrote", name)


if __name__ == "__main__":
    main()
