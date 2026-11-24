"""Draws a portrait with the very code you are reading.

The canvas is a listing of this file, over and over, on black. The photo
is never pasted: it only decides the weight and the light of each letter.

    python portrait.py photo.png fonts/ wide portrait.png
"""
import io
import keyword
import sys
import tokenize
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CELL_W, CELL_H, FONT_SIZE = 10, 12, 15
LAYOUTS = {  # columns, rows, and where the photo goes: left, top, width in columns
    "wide": (200, 99, 80, 3, 120),
    "tall": (132, 132, 4, 1, 124),
}
CROP = (0.06, 0.005, 0.94, 0.853)  # the part of the photo worth drawing
WEIGHTS = ["Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold"]
WHISPER = 0.13  # light of the listing around the person
PEAK = 0.64  # average light of the brightest cell
TINT = 0.45  # how much of the syntax color survives over the purple

PURPLE, LIGHTS = np.array((168, 124, 224.0)), np.array((250, 242, 255.0))
PALETTE = {
    "keyword": (190, 140, 255),
    "name": (176, 143, 208),
    "string": (110, 226, 165),
    "number": (255, 178, 92),
    "op": (245, 110, 160),
    "comment": (110, 175, 245),
}


def kind_of(token):
    if token.type == tokenize.STRING:
        return "string"
    if token.type == tokenize.NUMBER:
        return "number"
    if token.type == tokenize.COMMENT:
        return "comment"
    if token.type == tokenize.OP:
        return "op"
    return "keyword" if keyword.iskeyword(token.string) else "name"


def own_characters():
    """This file as (character, kind) pairs, without spaces or thin signs."""
    source = Path(__file__).read_text(encoding="utf-8")
    pairs = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        kind = kind_of(token)
        pairs += [(c, kind) for c in token.string if c.isalnum() or c in "@#%&()[]{}=+*/<>"]
    return pairs


def blurred(values, radius):
    picture = Image.fromarray((values * 255).astype(np.uint8))
    return np.asarray(picture.filter(ImageFilter.GaussianBlur(radius)), float) / 255


def light_grid(photo, layout):
    """Light from 0 to 1 for every cell of the canvas."""
    cols, rows, left, top, span = LAYOUTS[layout]
    image = Image.open(photo).convert("RGBA")
    image = image.crop([round(c * image.width) for c in CROP])
    alpha = np.asarray(image.getchannel("A"), float) / 255
    light = np.asarray(image.convert("RGB"), float) @ (0.2126, 0.7152, 0.0722) / 255
    low, high = np.percentile(light[alpha > 0.5], (1, 99.3))
    light = np.clip((light - low) / (high - low), 0, 1) ** 0.76
    detail = light - blurred(light, image.width / 45)
    lamp = blurred(light, image.width / 9) - 0.5
    light = np.clip(light + 0.7 * detail - 0.2 * lamp * (light > 0.25), 0, 1)

    tall = round(span * CELL_W * image.height / image.width / CELL_H)

    def to_cells(values):
        picture = Image.fromarray((values * 255).astype(np.uint8))
        return np.asarray(picture.resize((span, tall), Image.BOX), float) / 255

    person, cover = to_cells(light), to_cells(alpha)
    y, x = np.mgrid[0:rows, 0:cols]
    away = np.hypot((x - left - span / 2) / span, (y - rows * 0.45) / rows)
    grid = WHISPER * np.clip(1.35 - 1.5 * away, 0, 1)
    tall = min(tall, rows - top)
    part = grid[top : top + tall, left : left + span]
    columns = np.arange(span)
    inside = columns if left + span >= cols else np.minimum(columns, columns[::-1])
    edge = np.clip(inside / 16, 0, 1) ** 1.5  # so the edge of the photo never shows
    shown = np.maximum(person[:tall], 0.07) * edge
    floor = np.clip((tall - np.arange(tall)) / 22, 0, 1)[:, None] if top + tall < rows else 1
    part[:] = np.where(cover[:tall] > 0.45, np.maximum(shown * floor, part), part)
    return grid * np.clip((rows - y) / 9, 0, 1)


def glyph(char, weight, fonts, cache={}):
    """The letter as a mask of one cell, and how much ink it has."""
    if (char, weight) not in cache:
        mask = Image.new("L", (CELL_W, CELL_H))
        position = (CELL_W / 2, CELL_H / 2 + FONT_SIZE * 0.36)
        ImageDraw.Draw(mask).text(position, char, 255, fonts[weight], anchor="ms")
        mask = np.asarray(mask, float)[..., None] / 255
        cache[char, weight] = mask, mask.mean()
    return cache[char, weight]


def draw(grid, characters, fonts):
    rows, cols = grid.shape
    canvas = np.zeros((rows * CELL_H, cols * CELL_W, 4))
    used = 0
    for y, x in np.argwhere(grid > 0.012):
        char, kind = characters[used % len(characters)]
        used += 1
        light = grid[y, x]
        mask, ink = glyph(char, round(light**0.9 * (len(WEIGHTS) - 1)), fonts)
        color = PURPLE + (LIGHTS - PURPLE) * light**1.1
        tint = np.array(PALETTE[kind], float)
        color = color + (tint - color) * TINT * (1 - 0.55 * light)
        wanted = light * PEAK / ink  # thin letters shine more, thick ones less
        letter = np.clip(color * min(wanted, 1.0), 0, 255)
        rest = np.clip(light * PEAK - ink, 0, 1) / (1 - ink)  # only what the ink can't reach
        cell = canvas[y * CELL_H : (y + 1) * CELL_H, x * CELL_W : (x + 1) * CELL_W]
        cell[..., :3] = (PURPLE + color) * 0.5 * rest * (1 - mask) + letter * mask
        cell[..., 3:] = 255 * np.maximum(mask, rest)
        cell[..., :3] = np.where(cell[..., 3:] > 0, cell[..., :3] * 255 / np.maximum(cell[..., 3:], 1), 0).clip(0, 255)
    return Image.fromarray(canvas.astype(np.uint8)), used


def main(photo, font_folder, layout, target):
    characters = own_characters()
    files = [Path(font_folder) / f"JetBrainsMono-{w}.ttf" for w in WEIGHTS]
    fonts = [ImageFont.truetype(str(f), FONT_SIZE) for f in files]
    portrait, used = draw(light_grid(photo, layout), characters, fonts)
    portrait.save(target)
    print(f"{used} characters drawn, {len(characters)} in this file")


if __name__ == "__main__":
    main(*sys.argv[1:5])
