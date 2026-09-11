"""Draw docs/architecture.png.

The figure is generated rather than hand-drawn so it can be kept in step with
the code: if a stage is added, the picture is one edit away instead of one
afternoon in a drawing tool. Run it from the repository root:

    python docs/make_architecture.py

Only Pillow is needed, and only to run this script.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("architecture.png")
S = 2  # supersample, then downscale — the only antialiasing Pillow has

W, H = 1500, 890
BG = (255, 255, 255)
INK = (28, 26, 23)
MUTED = (110, 104, 95)
LINE = (138, 131, 117)

CARD = (244, 241, 234)
CARD_EDGE = (185, 178, 164)
COLD = (232, 238, 245)
COLD_EDGE = (107, 134, 168)
QUIET = (238, 240, 238)
QUIET_EDGE = (154, 163, 154)
GOLD = (253, 243, 227)
GOLD_EDGE = (200, 137, 47)

REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
ITALIC = "/System/Library/Fonts/Supplemental/Arial Italic.ttf"
# Arial Bold has no ★ glyph and Pillow draws a tofu box instead of falling back,
# so the star is drawn from the one font on the system that does have it.
UNICODE = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size * S)


F_TITLE = font(BOLD, 15)
F_BODY = font(REGULAR, 12)
F_SMALL = font(REGULAR, 11)
F_ITAL = font(ITALIC, 11)
F_CHIP = font(REGULAR, 11)
F_STAR = font(BOLD, 16)
F_STAR_GLYPH = font(UNICODE, 15)


def star(d, x, y, fill=(200, 137, 47)):
    """Draw ★ where and only where the font can actually render it."""
    d.text((x * S, y * S), "★", font=F_STAR_GLYPH, fill=fill)
    return d.textlength("★ ", font=F_STAR_GLYPH) / S

MARGIN = 32
COL_W = 344
GAP = 20
COLS = [MARGIN + i * (COL_W + GAP) for i in range(4)]


def box(d, x, y, w, h, fill=CARD, edge=CARD_EDGE, radius=10, width=1.6):
    d.rounded_rectangle(
        [x * S, y * S, (x + w) * S, (y + h) * S],
        radius=radius * S, fill=fill, outline=edge, width=int(width * S),
    )


def text(d, x, y, s, f, fill=INK):
    d.text((x * S, y * S), s, font=f, fill=fill)


def para(d, x, y, lines, f=F_BODY, fill=INK, leading=16):
    for i, line in enumerate(lines):
        text(d, x, y + i * leading, line, f, fill)


def arrow(d, x1, y1, x2, y2, dashed=False, label=None, label_offset=(0, -18)):
    d_ = d
    if dashed:
        # Manual dashes: Pillow has no dash support on lines.
        import math

        total = math.hypot(x2 - x1, y2 - y1)
        steps = max(int(total // 8), 1)
        for i in range(0, steps, 2):
            t0, t1 = i / steps, min((i + 1) / steps, 1.0)
            d_.line(
                [
                    ((x1 + (x2 - x1) * t0) * S, (y1 + (y2 - y1) * t0) * S),
                    ((x1 + (x2 - x1) * t1) * S, (y1 + (y2 - y1) * t1) * S),
                ],
                fill=LINE, width=int(1.6 * S),
            )
    else:
        d_.line([(x1 * S, y1 * S), (x2 * S, y2 * S)], fill=LINE, width=int(1.6 * S))

    # Arrowhead, always pointing along y or x.
    a = 5
    if abs(x2 - x1) > abs(y2 - y1):  # horizontal
        sgn = 1 if x2 > x1 else -1
        d_.polygon(
            [(x2 * S, y2 * S), ((x2 - sgn * a * 1.8) * S, (y2 - a) * S),
             ((x2 - sgn * a * 1.8) * S, (y2 + a) * S)],
            fill=LINE,
        )
    else:  # vertical
        sgn = 1 if y2 > y1 else -1
        d_.polygon(
            [(x2 * S, y2 * S), ((x2 - a) * S, (y2 - sgn * a * 1.8) * S),
             ((x2 + a) * S, (y2 - sgn * a * 1.8) * S)],
            fill=LINE,
        )

    if label:
        lx, ly = label_offset
        text(d_, (x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly, label, F_SMALL, MUTED)


def main() -> None:
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)

    # ---------------------------------------------------------------- row A
    y, h = 24, 172

    box(d, COLS[0], y, COL_W, h)
    text(d, COLS[0] + 16, y + 14, "Synthetic dataset", F_TITLE)
    para(d, COLS[0] + 16, y + 40, [
        "data/*.json — 26 modules and the",
        "prerequisite graph between them,",
        "degree requirements, 5 written rules,",
        "one student, her holds, the calendar.",
    ])
    para(d, COLS[0] + 16, y + 112, [
        "Deterministic: generate it twice and",
        "you get byte-identical files.",
    ], F_ITAL, MUTED, 15)

    box(d, COLS[1], y, COL_W, h)
    text(d, COLS[1] + 16, y + 14, "SchoolStore", F_TITLE)
    para(d, COLS[1] + 16, y + 40, [
        "Reads re-read from disk. Nothing is",
        "cached, because the agent's tools run",
        "in a different process and a cached",
        "course list goes stale the moment one",
        "of them takes a seat.",
    ])
    para(d, COLS[1] + 16, y + 128, [
        "Writes are atomic, one method per",
        "mutation, so a change cannot be lost.",
    ], F_ITAL, MUTED, 15)

    box(d, COLS[2], y, COL_W, h)
    text(d, COLS[2] + 16, y + 14, "Three specialists, as tools", F_TITLE)
    para(d, COLS[2] + 16, y + 40, [
        "Pathfinder — prerequisite chains and",
        "degree gaps; “can this still be closed?”",
        "Sentinel     — scans deadlines and reports",
        "irreversible? how many days? confidence",
        "Explainer — what a rule means.",
    ])
    star(d, COLS[2] + 16 + d.textlength("Sentinel ", font=F_BODY) / S, y + 71)
    para(d, COLS[2] + 16, y + 128, [
        "Facts, not verdicts. None of them",
        "decides whether to bother her.",
    ], F_ITAL, MUTED, 15)

    box(d, COLS[3], y, COL_W, h)
    text(d, COLS[3] + 16, y + 14, "Compass, the orchestrator", F_TITLE)
    para(d, COLS[3] + 16, y + 40, [
        "Observe → judge → act → record.",
        "",
        "It may act without asking only where",
        "the written programme rules determine",
        "the outcome completely.",
    ])
    para(d, COLS[3] + 16, y + 128, [
        "Everything else becomes a question.",
    ], F_ITAL, MUTED, 15)

    for i in range(3):
        x = COLS[i] + COL_W
        arrow(d, x + 3, y + h / 2, COLS[i + 1] - 3, y + h / 2)

    # ---------------------------------------------------------------- row B
    yb, hb = 232, 148
    box(d, MARGIN, yb, COLS[3] + COL_W - MARGIN, hb, GOLD, GOLD_EDGE, width=2.2)
    text(d, MARGIN + 20, yb + 16, "gate.py", F_STAR)
    gw = MARGIN + 20 + d.textlength("gate.py ", font=F_STAR) / S
    star(d, gw, yb + 15)
    text(d, gw + 22, yb + 16,
         "—  six deterministic rules, evaluated in a fixed order", F_STAR)

    chips = ["R1 low confidence", "R2 window closed", "R3 recoverable",
             "R4 no choice", "R5 > 45 days out", "R6 one-way door"]
    cx, cy = MARGIN + 20, yb + 50
    for i, c in enumerate(chips):
        cw = d.textlength(c, font=F_CHIP) / S + 22
        fill = GOLD if i == 5 else (255, 255, 255)
        edge = GOLD_EDGE if i == 5 else CARD_EDGE
        box(d, cx, cy, cw, 26, fill, edge, radius=13, width=1.4)
        text(d, cx + 11, cy + 7, c, F_CHIP)
        cx += cw + 9

    para(d, MARGIN + 20, yb + 90, [
        "The model establishes facts. The gate decides whether to interrupt, in plain Python — so the same finding on",
        "the same date always yields the same verdict, every verdict cites the rule that produced it, and silence is a",
        "decision with a recorded reason rather than an absence of output.",
    ], F_BODY, MUTED, 17)

    arrow(d, COLS[3] + COL_W / 2, 24 + h, COLS[3] + COL_W / 2, yb - 3)

    # ---------------------------------------------------------------- row C
    yc, hc = 420, 108
    cw3 = (COLS[3] + COL_W - MARGIN - 2 * GAP) / 3  # three equal columns
    xs = [MARGIN + i * (cw3 + GAP) for i in range(3)]

    box(d, xs[0], yc, cw3, hc, QUIET, QUIET_EDGE)
    text(d, xs[0] + 18, yc + 14, "SILENT", F_TITLE)
    para(d, xs[0] + 18, yc + 42, [
        "The reason is recorded and nothing",
        "happens. A silent agent that cannot",
        "show its work is indistinguishable",
        "from a broken one.",
    ], F_SMALL, MUTED, 15)

    box(d, xs[1], yc, cw3, hc, QUIET, QUIET_EDGE)
    text(d, xs[1] + 18, yc + 14, "AUTO_ACT", F_TITLE)
    para(d, xs[1] + 18, yc + 42, [
        "Runs only if the action is on",
        "AUTO_ACT_PERMITTED — two bookkeeping",
        "actions whose outcome the programme's",
        "written rules already fix.",
    ], F_SMALL, MUTED, 15)

    box(d, xs[2], yc, cw3, hc, GOLD, GOLD_EDGE, width=2.2)
    text(d, xs[2] + 18, yc + 14, "SURFACE", F_TITLE)
    para(d, xs[2] + 18, yc + 42, [
        "The only path to the student's",
        "attention in the entire system.",
        "Irreversible, inside the horizon, and",
        "genuinely her decision to make.",
    ], F_SMALL, MUTED, 15)

    for i in range(3):
        arrow(d, xs[i] + cw3 / 2, yb + hb, xs[i] + cw3 / 2, yc - 3)

    # ---------------------------------------------------------------- row D
    yd, hd = 592, 224

    box(d, MARGIN, yd, COLS[1] + COL_W - MARGIN, hd)
    text(d, MARGIN + 18, yd + 14, "actions.py — real side effects", F_TITLE)
    para(d, MARGIN + 18, yd + 42, [
        "Validates like the registrar would, then mutates,",
        "then writes a receipt. Seven actions; each one",
        "refuses the way the real system refuses, and every",
        "check runs before any mutation — a refused",
        "registration takes no seat.",
    ], F_BODY, INK, 16)

    iy = yd + 138
    box(d, MARGIN + 18, iy, COLS[1] + COL_W - MARGIN - 36, 68, COLD, COLD_EDGE, radius=8)
    text(d, MARGIN + 32, iy + 12, "receipts.jsonl", F_TITLE)
    para(d, MARGIN + 32, iy + 36, [
        "Append-only audit trail. Confirmation numbers are derived, not random,",
        "so re-running the demo produces the same receipt.",
    ], F_SMALL, MUTED, 15)

    box(d, COLS[2], yd, COLS[3] + COL_W - COLS[2], hd)
    text(d, COLS[2] + 18, yd + 14, "Where a person sees it", F_TITLE)

    bw = COLS[3] + COL_W - COLS[2] - 36
    box(d, COLS[2] + 18, yd + 42, bw, 84, GOLD, GOLD_EDGE, radius=8)
    text(d, COLS[2] + 32, yd + 54, "Decision card — FastAPI + SSE", F_BODY)
    para(d, COLS[2] + 32, yd + 76, [
        "Watching, with the silences and their reasons.",
        "Then a card: what happened, what it costs, why",
        "you are seeing it, and two or three buttons.",
    ], F_SMALL, MUTED, 15)

    box(d, COLS[2] + 18, yd + 136, bw, 70, COLD, COLD_EDGE, radius=8)
    text(d, COLS[2] + 32, yd + 148, "AgentCore Runtime — eu-west-1, CodeZip", F_BODY)
    para(d, COLS[2] + 32, yd + 170, [
        "POST /invocations · GET /ping.",
        "The same agent, behind the same contract.",
    ], F_SMALL, MUTED, 15)

    arrow(d, xs[1] + cw3 * 0.62, yc + hc, MARGIN + 120, yd - 3)
    arrow(d, xs[2] + cw3 * 0.55, yc + hc, COLS[2] + 120, yd - 3)
    arrow(d, xs[2] + cw3 * 0.85, yc + hc, xs[2] + cw3 * 0.85, yd - 3)

    # The dashed line runs below both cards so it crosses no text at all.
    y_loop = yd + hd + 34
    x_out = COLS[2] + 40
    x_in = MARGIN + 120
    d.line([(x_out * S, (yd + hd) * S), (x_out * S, y_loop * S)],
           fill=LINE, width=int(1.6 * S))
    arrow(d, x_out, y_loop, x_in, y_loop, dashed=True)
    arrow(d, x_in, y_loop, x_in, yd + hd + 3)
    text(d, (x_out + x_in) / 2 - 50, y_loop + 7, "she picks an option",
         F_SMALL, MUTED)

    img = img.resize((W, H), Image.LANCZOS)
    img.save(OUT)
    print(f"wrote {OUT} ({W}x{H})")


if __name__ == "__main__":
    main()
