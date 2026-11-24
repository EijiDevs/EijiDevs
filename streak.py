"""Draws the streak cards of the README from the public contribution calendar.

    GITHUB_TOKEN=... python streak.py EijiDevs assets
"""
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

QUERY = """query($login: String!) { user(login: $login) { contributionsCollection {
  contributionCalendar { weeks { contributionDays { date contributionCount } } } } } }"""

BACKGROUND, WHITE, PURPLE, MUTED, LINE, RULE = "#0b0a08", "#f6f2ee", "#c9a1ff", "#9a91a6", "#6b6278", "#352d42"


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    days: int
    margin: int
    figure_y: int
    figure: int
    label: int
    note: int
    chart_y: int
    chart_height: int
    radius: int
    stacked: bool = False


LAYOUTS = {
    "wide": Layout(1000, 400, 30, 48, 100, 68, 20, 17, 340, 120, 18),
    "tall": Layout(660, 800, 14, 48, 108, 84, 34, 28, 720, 250, 34, stacked=True),
}


class Type:
    """Text as vector paths: an SVG inside a README can't load fonts."""

    def __init__(self, path):
        self.font = TTFont(path)
        self.glyphs, self.names = self.font.getGlyphSet(), self.font.getBestCmap()
        self.units = self.font["head"].unitsPerEm

    def width(self, text, size, tracking=0):
        advance = sum(self.glyphs[self.names[ord(c)]].width for c in text) * size / self.units
        return advance + tracking * len(text)

    def draw(self, text, x, y, size, fill, tracking=0):
        scale, pen = size / self.units, SVGPathPen(self.glyphs, ntos=lambda n: f"{n:.1f}".rstrip("0").rstrip("."))
        for char in text:
            glyph = self.glyphs[self.names[ord(char)]]
            glyph.draw(TransformPen(pen, (scale, 0, 0, -scale, x, y)))
            x += glyph.width * scale + tracking
        return f'<path fill="{fill}" d="{pen.getCommands()}"/>'


def fetch_days(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    headers = {"Authorization": f"bearer {token}", "Content-Type": "application/json"}
    request = urllib.request.Request("https://api.github.com/graphql", body, headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        answer = json.load(response)
    if answer.get("errors"):
        raise RuntimeError(answer["errors"])
    weeks = answer["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [(date.fromisoformat(d["date"]), d["contributionCount"]) for w in weeks for d in w["contributionDays"]]


def streaks(days):
    """Current and longest streak. Today doesn't break a streak until it ends."""
    run, longest = [], []
    closed = days[:-1] if days[-1][1] == 0 else days
    for day, count in closed:
        run = run + [day] if count else []
        longest = max(longest, run, key=len)
    return run, longest


def short(day):
    return f"{day:%b} {day.day}"


def span(run):
    first, last = run[0], run[-1]
    if first == last:
        return short(first)
    return f"{short(first)} to {last.day if first.month == last.month else short(last)}"


def curve(counts, layout):
    left, right = layout.margin, layout.width - layout.margin
    top = max(max(counts), 1)
    points = [
        (left + (right - left) * i / (len(counts) - 1), layout.chart_y - layout.chart_height * n / top)
        for i, n in enumerate(counts)
    ]
    path = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        middle = (x0 + x1) / 2
        path += f"C{middle:.1f},{y0:.1f} {middle:.1f},{y1:.1f} {x1:.1f},{y1:.1f}"
    return path, points


def plural(count, word):
    return word if count == 1 else f"{word}s"


def card(days, layout, title, label, note):
    current, longest = streaks(days)
    busiest, top = max(days, key=lambda d: d[1])
    figures = [
        (len(current), "Current streak", f"{plural(len(current), 'day')} since {short(current[0])}" if current else "days", PURPLE),
        (len(longest), "Longest streak", f"{plural(len(longest), 'day')}, {span(longest)}" if longest else "days", WHITE),
        (top, "Busiest day", f"{plural(top, 'contribution')} on {short(busiest)}", WHITE),
    ]
    text = []
    for i, (value, name, detail, color) in enumerate(figures):
        if layout.stacked:
            x, y, aside = layout.margin, layout.figure_y + i * 126, 186
            text += [
                title.draw(str(value), x, y, layout.figure, color, -2),
                label.draw(name, x + aside, y - layout.note - 8, layout.label, WHITE),
                note.draw(detail, x + aside, y + 4, layout.note, MUTED),
            ]
            continue
        x, y = layout.margin + i * (layout.width - 2 * layout.margin) / 3, layout.figure_y
        if i:
            tall = layout.figure + layout.label + layout.note + 26
            text.append(f'<rect x="{x - 22:.0f}" y="{y - layout.figure + 6}" width="1" height="{tall}" fill="{RULE}"/>')
        text += [
            title.draw(str(value), x, y, layout.figure, color, -2),
            label.draw(name, x, y + layout.label + 12, layout.label, WHITE),
            note.draw(detail, x, y + layout.label + layout.note + 22, layout.note, MUTED),
        ]

    shown = days[-layout.days :]
    path, points = curve([count for _, count in shown], layout)
    in_streak = [i for i, (day, _) in enumerate(shown) if current and current[0] <= day]
    split = points[in_streak[0]][0] if in_streak else points[-1][0]
    last_x, last_y = points[-1]
    floor, right = layout.chart_y, layout.width - layout.margin
    area = f"{path}L{last_x:.1f},{floor}L{layout.margin},{floor}Z"
    first_label, last_label = short(shown[0][0]), short(shown[-1][0])
    baseline = floor + layout.note + 12
    described = ", ".join(f"{name.lower()}: {value} {detail}" for value, name, detail, _ in figures)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {layout.width} {layout.height}" role="img" aria-label="{described}">
<defs><linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{PURPLE}" stop-opacity=".38"/><stop offset="1" stop-color="{PURPLE}" stop-opacity="0"/></linearGradient>
<clipPath id="now"><rect x="{split:.1f}" y="0" width="{layout.width}" height="{layout.height}"/></clipPath><clipPath id="before"><rect x="0" y="0" width="{split:.1f}" height="{layout.height}"/></clipPath></defs>
<rect width="{layout.width}" height="{layout.height}" rx="{layout.radius}" fill="{BACKGROUND}"/>
{"".join(text)}
<path d="{area}" fill="{MUTED}" fill-opacity=".1" clip-path="url(#before)"/><path d="{area}" fill="url(#fade)" clip-path="url(#now)"/>
<path d="{path}" fill="none" stroke="{LINE}" stroke-width="2.5" clip-path="url(#before)"/><path d="{path}" fill="none" stroke="{PURPLE}" stroke-width="3.5" stroke-linecap="round" clip-path="url(#now)"/>
<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="6" fill="{PURPLE}" stroke="{BACKGROUND}" stroke-width="3"/>
{note.draw(first_label, layout.margin, baseline, layout.note, MUTED)}{note.draw(last_label, right - note.width(last_label, layout.note), baseline, layout.note, MUTED)}
</svg>
"""


def main(login, folder):
    folder = Path(folder)
    fonts = [Type(folder / "fonts" / name) for name in ("title.ttf", "label.ttf", "note.ttf")]
    days = fetch_days(login, os.environ["GITHUB_TOKEN"])
    for name, layout in LAYOUTS.items():
        (folder / f"streak-{name}.svg").write_text(card(days, layout, *fonts), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:3])
