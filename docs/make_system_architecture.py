"""Draw docs/system_architecture.png: the end-to-end system, layer by layer.

    py -3.11 docs\\make_system_architecture.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("system_architecture.png")
W, H = 2900, 2030
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


def label_step(cx, cy, text, n):
    """A label with its flow number sitting just left of it."""
    label(cx, cy, text)
    step(cx - tw(text, F_LBL) / 2 - 34, cy, n)


def step(cx, cy, n, r=19):
    """A numbered circle marking a point in the end-to-end flow."""
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BLACK)
    s = str(n)
    d.text((cx - tw(s, F_H2) / 2, cy - F_H2.size / 2 - 2), s, font=F_H2, fill=WHITE)


# ---------------------------------------------------------------------------
t = "AI ASD Speech Improvement System  —  System Architecture"
d.text(((W - tw(t, F_TITLE)) / 2, 28), t, font=F_TITLE, fill=BLACK)
sub = "End to end: what the child and the doctor use, what the server does with speech, where data lives.  Numbers follow one practice attempt.  Dashed arrows leave the machine."
d.text(((W - tw(sub, F_SUB)) / 2, 88), sub, font=F_SUB, fill=BLACK)

# users ------------------------------------------------------------------------
box(300, 140, 680, 100, "CHILD  (browser + microphone)", ["practises · plays the arcade · does today's task · watches lessons"])
box(1840, 140, 680, 100, "DOCTOR / THERAPIST  (browser)", ["adds students · follows progress · sets tasks · uploads lessons"])
arrow([(620, 240), (620, 290)]); arrow([(2180, 240), (2180, 290)]); step(2230, 265, 6)

# presentation layer ------------------------------------------------------------
box(80, 290, 2640, 380, "PRESENTATION LAYER  —  plain HTML pages, no build step, phone to desktop", title_font=F_H1, dashed=True)
box(120, 380, 380, 250, "Sign-in", ["one page for both roles", "Child / Doctor selector", "receives a JWT and keeps it in the browser"])
box(540, 380, 760, 250, "Child App", [
    "Home · Training · Deep Training · Today's Task · Video Lessons · My Progress · Transcribe",
    "records the microphone: WebM/Opus → 16 kHz WAV in the browser",
    "shows verdict, stars, confetti; the buddy character speaks the feedback",
])
box(1340, 380, 520, 250, "Arcade Mode", [
    "six speaking games: Say & Catch, Balloon Speech, Feed the Animal, Sound Match, Build the Word, Treasure Hunt",
    "levels: Words → Simple → Longer sentences",
])
box(1900, 380, 780, 250, "Doctor Dashboard", [
    "Overview · Students (add, invite, detail) · Today's Task · Video Lessons · Settings",
    "progress per child and per category, deep-training queue, recent attempts",
])

# application server -------------------------------------------------------------
box(80, 760, 2640, 260, "APPLICATION SERVER  —  FastAPI (Python), REST + JSON, one process", title_font=F_H1)
box(120, 850, 560, 140, "JWT Authentication & Role Access", ["verifies signature, expiry, revocation, token version", "role claim: doctor | student  →  each route checks it"])
box(720, 850, 600, 140, "Speech endpoints", ["transcribe · practice · check · arcade pick", "bounded worker pool: one CPU inference at a time"])
box(1360, 850, 600, 140, "Content endpoints", ["lexicon · pronounce / slow · say · feedback", "deep-training steps"])
box(2000, 850, 680, 140, "Portal endpoints", ["students & invites · attempts & progress", "tasks & results · video lessons · calendar"])

arrow([(1010, 670), (1010, 760)], both=True); label_step(1010, 715, "audio + expected text  /  verdict", 2)
arrow([(1660, 670), (1660, 760)], both=True); label_step(1660, 715, "lesson list · voice clips · steps", 1)
arrow([(2340, 670), (2340, 760)], both=True); label_step(2340, 715, "bearer JWT · students, tasks, lessons, attempts", 5)

# speech assessment pipeline -------------------------------------------------------
box(80, 1100, 1560, 620, "SPEECH ASSESSMENT PIPELINE  —  runs entirely on this machine, CPU", title_font=F_H1, dashed=True)
CY, CH, CW = 1190, 240, 270
box(120, CY, CW, CH, "Audio decoder", ["any upload format → mono 16 kHz", "long audio split at silences"])
box(420, CY, CW, CH, "ASR engine", ["AI4Bharat IndicConformer 600M", "RNNT decoding · PyTorch", "Tamil speech → Tamil text"])
box(720, CY, CW, CH, "Romaniser", ["Tamil script → English letters", "rule-based, deterministic"])
box(1020, CY, CW, CH, "Scorer", ["edit-distance similarity on script and on roman; best wins", "containment guard for short targets"])
box(1320, CY, CW, CH, "Verdict", ["≥ 0.85 correct · ≥ 0.55 close · else incorrect · no speech", "score % · best match among options"])
for x in (390, 690, 990, 1290):
    arrow([(x, CY + CH / 2), (x + 30, CY + CH / 2)])
step(1300, 1130, 3)

box(120, 1470, 270, 200, "Bounded worker pool", ["inference runs off the event loop", "the UI stays responsive"])
box(420, 1470, 270, 200, "Model weights", ["local cache, loaded once at start", "pinned revision"])
arrow([(555, CY + CH), (555, 1470)], both=True)
box(720, 1470, 880, 230, "How one practice attempt works", [
    "1  Child taps Pronounce: the cached neural voice clip plays",
    "2  Child records; the browser converts to 16 kHz WAV and sends it with the target text",
    "3  Decoder → ASR → romaniser → scorer → verdict",
    "4  Verdict, score and stars come back; the buddy speaks the feedback",
    "5  The attempt is stored under the child's account",
    "6  The doctor's dashboard shows it; the doctor sets tasks and lessons in return",
])

# server -> pipeline and back
arrow([(900, 990), (900, 1050), (255, 1050), (255, CY)]); label(560, 1050, "audio + target text")
arrow([(1455, CY), (1455, 1050), (1140, 1050), (1140, 990)]); label_step(1300, 1050, "verdict + score", 4)

# learning content & voice -----------------------------------------------------------
box(1700, 1100, 1020, 300, "LEARNING CONTENT & VOICE", title_font=F_H1, dashed=True)
box(1740, 1190, 300, 190, "Lesson list", ["12 vowels · 20 words · 10 short · 10 long sentences", "Tamil, roman, meaning, level"])
box(2060, 1190, 300, 190, "Deep-training steps", ["word → vowel → syllables → slow → full", "sentence → words → build-up"])
box(2380, 1190, 300, 190, "Pronunciation engine", ["neural Tamil voice, normal and slow", "spoken feedback phrases"])
arrow([(1830, 990), (1830, 1100)], both=True); label(1830, 1045, "lesson list · clips · steps")

# data layer --------------------------------------------------------------------------
box(1700, 1440, 1020, 260, "DATA LAYER", title_font=F_H1, dashed=True)
box(1740, 1530, 460, 150, "PostgreSQL", ["doctors · students · attempts · item progress", "deep state · tasks & results · lessons & views · revoked tokens"])
box(2220, 1530, 220, 150, "File storage", ["student photos", "lesson videos, streamed"])
box(2460, 1530, 220, 150, "Voice cache", ["one clip per item and speed", "rendered once"])
arrow([(2560, 1380), (2560, 1530)], both=True); label(2560, 1440, "render once, then read")
# portal endpoints -> data layer, down the right margin
arrow([(2680, 920), (2800, 920), (2800, 1600), (2720, 1600)]); label(2800, 1260, ["accounts", "progress", "tasks", "lessons"])

# external services ---------------------------------------------------------------------
EY = 1830
box(420, EY, 270, 110, "Hugging Face Hub", ["model weights, first run only"], dashed=True)
box(1740, EY, 460, 110, "SMTP server", ["invitation e-mail with the activation link"], dashed=True)
box(2380, EY, 340, 110, "Microsoft Edge TTS", ["synthesis when a clip is not cached"], dashed=True)
arrow([(555, 1670), (555, EY)], dashed=True)
arrow([(2560, 1680), (2560, EY)], dashed=True)
arrow([(2800, 1600), (2800, 1985), (1970, 1985), (1970, EY + 110)], dashed=True); label(2400, 1985, "invite e-mail, when SMTP is configured")

img.save(OUT)
print(OUT, img.size)
