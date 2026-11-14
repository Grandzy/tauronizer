"""Generate the add-on store icon and logo (development helper).

Requires Pillow (``pip install Pillow``), which is not a runtime dependency.
Run from the repository root:

    python tauronizer/scripts/make_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (15, 23, 42, 255)
AMBER = (245, 179, 26, 255)
WHITE = (248, 250, 252, 255)
MUTED = (148, 163, 184, 255)
S = 4  # supersampling factor
OUT = Path(__file__).resolve().parent.parent
FONT = "C:/Windows/Fonts/arialbd.ttf"


def draw_bolt(draw: ImageDraw.ImageDraw, cx: float, cy: float, height: float) -> None:
    width = height * 0.62
    points = [
        (cx - width * 0.10, cy - height / 2),
        (cx + width * 0.52, cy - height / 2),
        (cx + width * 0.18, cy - height * 0.08),
        (cx + width * 0.48, cy - height * 0.08),
        (cx - width * 0.30, cy + height / 2),
        (cx - width * 0.08, cy + height * 0.10),
        (cx - width * 0.42, cy + height * 0.10),
    ]
    draw.polygon(points, fill=AMBER)


def make_icon() -> None:
    size = 256
    image = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [0, 0, size * S - 1, size * S - 1], radius=56 * S, fill=BG
    )
    draw.ellipse(
        [34 * S, 34 * S, (size - 34) * S, (size - 34) * S],
        outline=(30, 41, 59, 255),
        width=10 * S,
    )
    draw_bolt(draw, size / 2 * S, size / 2 * S, 132 * S)
    image.resize((size, size), Image.LANCZOS).save(OUT / "icon.png")


def fit_font(draw, text: str, available: int, start: int, minimum: int):
    size = start
    while size > minimum:
        font = ImageFont.truetype(FONT, size * S)
        if draw.textlength(text, font=font) / S <= available:
            return font
        size -= 1
    return ImageFont.truetype(FONT, minimum * S)


def make_logo() -> None:
    width, height = 512, 256
    image = Image.new("RGBA", (width * S, height * S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [0, 0, width * S - 1, height * S - 1], radius=44 * S, fill=BG
    )
    draw.ellipse(
        [28 * S, 52 * S, 208 * S, 232 * S],
        outline=(30, 41, 59, 255),
        width=8 * S,
    )
    draw_bolt(draw, 118 * S, 142 * S, 118 * S)

    title_font = fit_font(draw, "Tauronizer", 232, 54, 28)
    subtitle = "TARYFY ENERGII POD LUPĄ"
    subtitle_font = fit_font(draw, subtitle, 232, 16, 10)

    draw.text((244 * S, 118 * S), "Tauronizer", font=title_font, fill=WHITE, anchor="ls")
    draw.text(
        (245 * S, 150 * S), subtitle, font=subtitle_font, fill=MUTED, anchor="ls"
    )
    draw.rectangle([245 * S, 172 * S, 275 * S, 178 * S], fill=AMBER)
    image.resize((width, height), Image.LANCZOS).save(OUT / "logo.png")


if __name__ == "__main__":
    make_icon()
    make_logo()
    print("Wrote icon.png and logo.png to", OUT)
