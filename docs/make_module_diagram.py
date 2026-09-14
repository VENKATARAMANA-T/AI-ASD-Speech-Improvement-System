"""Draw docs/module_architecture.png: the modules and how they talk, no file names.

    py -3.11 docs\\make_module_diagram.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("module_architecture.png")
W, H = 2760, 1840
BLACK, WHITE = (0, 0, 0), (255, 255, 255)
FONTS = Path(r"C:\Windows\Fonts")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("arialbd.ttf" if bold else "arial.ttf")), size)


F_TITLE, F_SUB, F_H1, F_H2, F_BODY, F_LBL, F_SMALL = font(48, True), font(23), font(32, True), font(25, True), font(21), font(20), font(18)

img = Image.new("RGB", (W, H), WHITE)
d = ImageDraw.Draw(img)


def tw(s: str, f) -> int:
    return int(d.textlength(s, font=f))


def wrap(s: str, f, width: int) -> list[str]:
    words, lines, cur = s.split(" "), [], ""
    for w_ in words:
        cand = (cur + " " + w_).strip()
        if tw(cand, f) <= width or not cur:
            cur = cand
        else:
            lines.append(cur); cur = w_
    if cur:
        lines.append(cur)
    return lines


def box(x, y, w, h, title, lines=(), *, width=3, dashed=False, title_font=F_H2, body_font=F_BODY):
    if dashed:
        dash_rect(x, y, w, h, width)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=14, outline=BLACK, width=width, fill=WHITE)
    inner = w - 32
    ty = y + 12
    for t in wrap(title, title_font, inner):
        d.text((x + 16, ty), t, font=title_font, fill=BLACK); ty += title_font.size + 8
    ty += 4
    for line in lines:
        for t in wrap(line, body_font, inner):
            d.text((x + 16, ty), t, font=body_font, fill=BLACK); ty += body_font.size + 7
    assert ty <= y + h, f"overflow in box {title!r}: {ty} > {y + h}"


def dash_rect(x, y, w, h, width=3):
    for a, b in (((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y))):
        dash_line(a, b, width)


def dash_line(a, b, width=3, dash=18, gap=12):
    (x1, y1), (x2, y2) = a, b
    length = math.hypot(x2 - x1, y2 - y1)
    if not length:
        return
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    pos = 0.0
    while pos < length:
        end = min(pos + dash, length)
        d.line((x1 + ux * pos, y1 + uy * pos, x1 + ux * end, y1 + uy * end), fill=BLACK, width=width)
        pos += dash + gap


def head(tip, frm, size=16):
    ang = math.atan2(tip[1] - frm[1], tip[0] - frm[0])
    p1 = (tip[0] - size * math.cos(ang - 0.45), tip[1] - size * math.sin(ang - 0.45))
    p2 = (tip[0] - size * math.cos(ang + 0.45), tip[1] - size * math.sin(ang + 0.45))
    d.polygon([tip, p1, p2], fill=BLACK)


def arrow(points, *, both=False, dashed=False, width=3):
    pts = [tuple(p) for p in points]
    for a, b in zip(pts, pts[1:]):
        if dashed:
            dash_line(a, b, width)
        else:
            d.line((*a, *b), fill=BLACK, width=width)
    head(pts[-1], pts[-2])
    if both:
        head(pts[0], pts[1])


def label(cx, cy, lines, *, f=F_LBL, pad=8, anchor="center"):
    """Text on a white patch so it stays readable where it sits on a line."""
    if isinstance(lines, str):
        lines = [lines]
    w = max(tw(s, f) for s in lines) + pad * 2
    h = len(lines) * (f.size + 6) + pad * 2 - 6
    x = {"center": cx - w / 2, "left": cx, "right": cx - w}[anchor]
    y = cy - h / 2
    d.rectangle((x, y, x + w, y + h), fill=WHITE)
    ty = y + pad
    for s in lines:
        d.text((x + pad, ty), s, font=f, fill=BLACK); ty += f.size + 6


# ---------------------------------------------------------------------------
t = "Tamil Tutor  —  Module Architecture"
d.text(((W - tw(t, F_TITLE)) / 2, 28), t, font=F_TITLE, fill=BLACK)
sub = "The modules of the system and what flows between them.  Solid arrows are calls inside the server; dashed arrows go to services outside it."
d.text(((W - tw(sub, F_SUB)) / 2, 88), sub, font=F_SUB, fill=BLACK)

# actors ----------------------------------------------------------------------
box(400, 150, 600, 90, "CHILD  (web browser)", ["practises · does today's task · watches lessons"])
box(1740, 150, 600, 90, "DOCTOR  (web browser)", ["adds students · sets tasks · uploads lessons"])

# front end -------------------------------------------------------------------
box(80, 300, 2600, 260, "WEB FRONT END  (browser)", title_font=F_H1, dashed=True)
box(120, 400, 1160, 130, "Child App", [
    "sign-in · Home · Today's Task · Video Lessons · Training · Deep Training · Transcribe · My Progress · Character",
    "records the microphone · shows verdict and stars · Buddy character speaks the feedback",
])
box(1400, 400, 1280, 130, "Doctor Dashboard", [
    "Dashboard · Students (add, invite, detail) · Today's Task · Video Lessons · Settings",
    "opens only with a doctor session",
])

# server ----------------------------------------------------------------------
box(80, 660, 2600, 870, "SERVER  —  FastAPI, runs locally", title_font=F_H1, width=4)
box(120, 730, 2560, 110, "HTTP API", [
    "one application · speech routes (transcribe, practise, check, pronounce) and portal routes (auth, doctor, student)",
    "every portal route checks the caller's role before it does anything",
])

SY, SH, SW = 950, 540, 580
SX = [120, 760, 1400, 2040]

# 1. speech assessment
sx = SX[0]
box(sx, SY, SW, SH, "Speech assessment", width=3)
box(sx + 30, 1005, 520, 100, "Audio decoder", ["upload or mic clip → 16 kHz mono · silence guard"])
box(sx + 30, 1155, 520, 110, "Speech recognition", ["AI4Bharat IndicConformer 600M · RNNT decoding", "runs on the local CPU, no cloud, no API key"])
box(sx + 30, 1310, 240, 165, "Scoring & verdict", ["expected vs heard · score %", "correct / close / incorrect / no speech"])
box(sx + 310, 1310, 240, 165, "Romanizer", ["Tamil → English letters", "rule based"])
arrow([(sx + 290, 1105), (sx + 290, 1155)])
label(sx + 290, 1130, "waveform", f=F_SMALL)
arrow([(sx + 150, 1265), (sx + 150, 1310)])
label(sx + 150, 1290, "Tamil transcript", f=F_SMALL)
arrow([(sx + 310, 1390), (sx + 270, 1390)])
label(sx + 290, 1365, "roman", f=F_SMALL)

# 2. lesson content
sx = SX[1]
box(sx, SY, SW, SH, "Lesson content", width=3)
box(sx + 30, 1050, 520, 150, "Lexicon", ["12 vowels · 20 words · 10 short and 10 long sentences", "each with Tamil, English letters, meaning and level"])
arrow([(sx + 290, 1200), (sx + 290, 1290)])
label(sx + 290, 1245, "entry", f=F_SMALL)
box(sx + 30, 1290, 520, 150, "Deep-training decomposer", ["word → syllables → slow → full word", "sentence → words → build-up → full sentence"])

# 3. voice
sx = SX[2]
box(sx, SY, SW, SH, "Voice", width=3)
box(sx + 30, 1010, 240, 140, "Pronunciation", ["reference audio for any entry, normal and slow"])
box(sx + 310, 1010, 240, 140, "Feedback voice", ["spoken 'well done' / 'try again' phrases"])
arrow([(sx + 150, 1150), (sx + 150, 1230)])
arrow([(sx + 430, 1150), (sx + 430, 1230)])
label(sx + 290, 1190, "text", f=F_SMALL)
box(sx + 30, 1230, 520, 150, "Text-to-speech + audio cache", ["neural Tamil voice", "each clip rendered once, then served from disk"])

# 4. portal
sx = SX[3]
box(sx, SY, SW, SH, "Portal", width=3)
box(sx + 30, 1010, 240, 190, "Auth & roles", ["sign-in · JWT tokens", "doctor / child role checks"])
box(sx + 310, 1010, 240, 190, "PostgreSQL", ["doctors, students, progress, attempts, tasks, videos"])
arrow([(sx + 270, 1105), (sx + 310, 1105)], both=True)
box(sx + 30, 1270, 240, 190, "Media storage", ["student photos", "lesson videos, streamed"])
box(sx + 310, 1270, 240, 190, "Mailer", ["invitation e-mail with the activation link"])

# external services -------------------------------------------------------------
EY = 1650
box(120, EY, 580, 100, "Hugging Face Hub", ["model weights"], dashed=True)
box(1400, EY, 580, 100, "Microsoft Edge TTS", ["neural Tamil voice"], dashed=True)
box(2040, EY, 580, 100, "SMTP server", ["outgoing mail"], dashed=True)

# arrows -----------------------------------------------------------------------
# actors <-> front end
arrow([(700, 240), (700, 400)], both=True)
label(715, 345, ["taps · speaks into the microphone", "← pages, verdict, stars, buddy voice"], anchor="left")
arrow([(2040, 240), (2040, 400)], both=True)
label(2025, 345, ["student form, task, video upload", "← dashboards, progress, results"], anchor="right")

# front end <-> api
arrow([(700, 530), (700, 730)], both=True)
label(715, 610, ["audio clip + expected item  → ← verdict, score, heard text",
                 "item / phrase → ← reference mp3",
                 "child session → ← progress, tasks, lessons"], anchor="left")
arrow([(2040, 530), (2040, 730)], both=True)
label(2025, 610, ["doctor session → ← students, progress, results",
                  "student form, task, video file → ← invite link",
                  "sign-in → ← session token"], anchor="right")
arrow([(1280, 465), (1400, 465)])
label(1340, 440, "doctor session", f=F_SMALL)

# api <-> subsystems
for cx, lines in zip((410, 1050, 1690, 2330), (
    ["audio + expected text", "← verdict, score, heard text"],
    ["item id", "← entry · drill steps"],
    ["text, speed", "← mp3"],
    ["credentials, session, records", "← role, data, files"],
)):
    arrow([(cx, 840), (cx, SY)], both=True)
    label(cx, 895, lines)

# external
arrow([(410, SY + SH), (410, EY)], dashed=True)
label(410, 1590, ["model weights, downloaded once", "then cached locally"])
arrow([(1690, SY + SH), (1690, EY)], both=True, dashed=True)
label(1690, 1590, ["text  → ← mp3", "only the first time a clip is rendered"])
arrow([(2470, SY + SH), (2470, EY)], dashed=True)
label(2470, 1590, "invitation e-mail")

# legend -------------------------------------------------------------------------
lx, ly = 780, EY - 10
d.text((lx, ly), "Legend", font=F_H2, fill=BLACK)
d.line((lx, ly + 52, lx + 60, ly + 52), fill=BLACK, width=3); head((lx + 60, ly + 52), (lx, ly + 52))
d.text((lx + 72, ly + 40), "call inside the server", font=F_BODY, fill=BLACK)
dash_line((lx, ly + 90), (lx + 60, ly + 90)); head((lx + 60, ly + 90), (lx, ly + 90))
d.text((lx + 72, ly + 78), "call to an external service", font=F_BODY, fill=BLACK)
d.line((lx, ly + 128, lx + 60, ly + 128), fill=BLACK, width=3); head((lx + 60, ly + 128), (lx, ly + 128)); head((lx, ly + 128), (lx + 60, ly + 128))
d.text((lx + 72, ly + 116), "request and response", font=F_BODY, fill=BLACK)

img.save(OUT, optimize=True)
print(OUT, img.size)
