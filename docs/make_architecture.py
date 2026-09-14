"""Draw docs/architecture.png: the whole system, black on white.

    py -3.11 docs\\make_architecture.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("architecture.png")
W, H = 2800, 1860
BLACK, WHITE = (0, 0, 0), (255, 255, 255)
FONTS = Path(r"C:\Windows\Fonts")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("arialbd.ttf" if bold else "arial.ttf")), size)


F_TITLE, F_SUB, F_H1, F_H2, F_BODY, F_LBL, F_SMALL = font(46, True), font(22), font(30, True), font(24, True), font(20), font(19), font(17)

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


def vlabel(cx, cy, text, *, f=F_SMALL):
    """A label rotated 90° (reads bottom-to-top) for a vertical connector."""
    w, h = tw(text, f) + 12, f.size + 10
    tile = Image.new("RGB", (w, h), WHITE)
    ImageDraw.Draw(tile).text((6, 4), text, font=f, fill=BLACK)
    tile = tile.rotate(90, expand=True)
    img.paste(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)))


# ---------------------------------------------------------------------------
t = "Tamil Tutor  —  System Architecture"
d.text(((W - tw(t, F_TITLE)) / 2, 28), t, font=F_TITLE, fill=BLACK)
sub = "One server, two roles: the child app and the doctor's dashboard share one FastAPI process, one database and one sign-in.  Every arrow is labelled with what flows along it."
d.text(((W - tw(sub, F_SUB)) / 2, 84), sub, font=F_SUB, fill=BLACK)

# actors ----------------------------------------------------------------------
box(100, 160, 560, 110, "CHILD  (web browser)", ["signs in as Child · practises · does today's task · watches lessons"])
box(2140, 160, 560, 110, "DOCTOR  (web browser)", ["signs in as Doctor · adds students · sets tasks · uploads lessons"])

# the one server -----------------------------------------------------------------
box(60, 350, 2680, 1170, "TAMIL TUTOR SERVER  —  TamilSpeechDetection  (FastAPI, port 8000)", title_font=F_H1, width=4)

# front ends
box(100, 410, 1240, 190, "Child app  —  web/index.html  (single page, hash routes)", [
    "Sign-in page for BOTH roles (dropdown: Child / Doctor) · Activate (from the invite link)",
    "Home (daily-task calendar) · Today's Task · Video Lessons · Training · Deep Training · Transcribe · My Progress · Character · Settings",
    "Buddy character (inline SVG + CSS): mood by stars, speaks the verdict and the correct word",
    "localStorage: child token · progress · deep-training state · chosen buddy · voice language",
])
box(1460, 410, 1240, 190, "Doctor dashboard  —  web/doctor.html  (single page)", [
    "Opens only with a doctor token (otherwise back to the sign-in page)",
    "Dashboard (KPIs, open tasks, activity) · Students (cards, add / delete, invite link) · Student detail (progress, deep-training queue, tasks, videos, attempts)",
    "Today's Task (kind, level, deadline → broadcast) · Video Lessons (upload, who watched, delete) · Settings",
    "localStorage: doctor token",
])

# the API
box(100, 740, 2600, 170, "HTTP API  —  src/api.py  +  src/portal/api.py  (one app; every /api route checks the session's role)", [
    "Speech:  POST /transcribe  POST /practice  POST /check  GET /lexicon  GET /romanize  GET /deep/{id}  GET /pronounce/{id}  GET /say  GET /feedback/{key}  GET /health",
    "Auth:  POST /api/auth/login {role, identifier, password}  GET /api/auth/me  POST /api/auth/logout  ·  invites: GET /api/invites/{t}  POST /api/invites/{t}/activate",
    "Doctor role (require_doctor):  /api/doctor/students, /photo, /invite · /api/doctor/tasks · /api/doctor/videos · /api/doctor/overview · /api/doctor/password",
    "Child role (require_student):  /api/student/me, /progress, /attempts, /deep, /tasks, /videos, /calendar  ·  files: /photos/{name}  /videos/{name}?t=token",
])

# modules
R1, R2, BH, BW = 1000, 1270, 215, 300
C = [100, 440, 780, 1120, 1460, 1800, 2140]
box(C[0], R1, BW, BH, "ASR engine — src/asr.py", ["AI4Bharat IndicConformer 600M", "PyTorch, CPU, runs locally", "no API key · RNNT / CTC"])
box(C[1], R1, BW, BH, "Scoring — scoring.py, translit.py", ["expected vs heard text", "verdict: correct / close / incorrect / no_speech", "score % · romanisation"])
box(C[2], R1, BW, BH, "Lexicon — src/lexicon.py", ["12 vowels · 20 words", "10 short · 10 long sentences", "Tamil, roman, meaning", "levels Easy / Medium / Hard"])
box(C[3], R1, BW, BH, "TTS + cache — tts.py", ["pronounce.py, feedback.py", "Microsoft neural voices (edge-tts)", "mp3 cached on disk, rendered once"])
box(C[4], R1, BW, BH, "JWT & roles — security.py", ["src/portal · PBKDF2 password hashes", "signed JWT bearer tokens with a role claim: doctor | student (RBAC)"])
box(C[5], R1, BW, BH, "PostgreSQL — portal/db.py", ["doctors · students · tokens", "item_progress · attempts · deep_state", "tasks · task_results · videos · video_views"])
box(C[6], R1, 560, BH, "Files — data/", ["photos/  student photos", "videos/  uploaded lessons (random names, streamed with Range)"])
box(C[1], R2, BW, BH, "Decomposer — decompose.py", ["word → sound pieces → syllables → slow → full word", "drill steps for Deep Training"])
box(C[5], R2, BW, BH, "Mailer — src/portal/mailer.py", ["invite e-mail over SMTP", "if SMTP is not configured the link is shown in the dashboard"])

# external services ---------------------------------------------------------------
EY = 1680
box(100, EY, 460, 110, "Hugging Face Hub", ["gated model repository"], dashed=True)
box(880, EY, 460, 110, "Microsoft Edge TTS service", ["neural Tamil and English voices"], dashed=True)
box(1700, EY, 460, 110, "SMTP server  (e.g. Gmail)", ["outgoing mail"], dashed=True)
box(2240, EY, 460, 110, "Child's e-mail inbox", ["receives the invitation"], dashed=True)

# arrows ----------------------------------------------------------------------------
# actors <-> front ends
arrow([(660, 215), (1200, 215), (1200, 410)], both=True)
label(1215, 330, ["opens the app · picks the Child role", "microphone audio (MediaRecorder)", "← pages, verdict + stars, buddy voice"], anchor="left")
arrow([(2420, 270), (2420, 410)], both=True)
label(2405, 340, ["opens the app · picks the Doctor role · student form + photo · task · video upload", "← dashboards, student progress, task results, who watched"], anchor="right")

# front ends <-> api
arrow([(330, 600), (330, 740)], both=True)
label(345, 670, ["{role: child, identifier, password} → /api/auth/login   ← child token",
                 "audio clip + entry_id / text → /practice, /check   ← verdict, score %, heard text",
                 "entry_id / text / phrase key → /pronounce, /say, /feedback   ← mp3",
                 "Bearer child token → /api/student/*   ← progress, today's tasks, lessons, calendar"], anchor="left")
arrow([(1560, 600), (1560, 740)], both=True)
label(1575, 670, ["{role: doctor, identifier, password} → /api/auth/login   ← doctor token",
                  "Bearer doctor token → /api/doctor/*   ← students, progress, task results, watch counts",
                  "student form + photo · task (kind, level, deadline) · video file (multipart)",
                  "← invite link · upload progress and result"], anchor="left")
# the sign-in page hands the doctor token to the dashboard page
arrow([(1340, 560), (1460, 560)])
label(1400, 535, ["doctor", "token →", "/doctor.html"], f=F_SMALL)

# api -> modules (row 1)
arrow([(250, 910), (250, R1)])
label(250, 955, "16 kHz mono waveform")
arrow([(590, 910), (590, R1)], both=True)
label(590, 955, ["expected entry + transcript", "← verdict, score, stars"])
arrow([(930, 910), (930, R1)], both=True)
label(930, 955, ["entry_id", "← entry, category, level, roman"])
arrow([(1270, 910), (1270, R1)], both=True)
label(1270, 955, ["Tamil word / phrase", "← mp3 (cache)"])
arrow([(1610, 910), (1610, R1)], both=True)
label(1610, 955, ["password, token", "← ok? which role?"])
arrow([(1950, 910), (1950, R1)], both=True)
label(1950, 955, "SQL reads / writes")
arrow([(2420, 910), (2420, R1)], both=True)
label(2420, 955, "photo / video bytes")
# asr -> scoring
arrow([(C[0] + BW, 1180), (C[1], 1180)])
label(420, 1200, "transcript", f=F_SMALL)
# row 1 -> row 2
arrow([(1950, R1 + BH), (1950, R2)])
label(1950, 1242, "student name, e-mail, activation link")
# api -> decomposer via the gap
arrow([(420, 910), (420, 1370), (C[1], 1370)], both=True)
vlabel(420, 1040, "entry_id  →   ← drill steps")

# external
arrow([(C[0], 1060), (78, 1060), (78, 1640), (330, 1640), (330, EY)], dashed=True)
label(95, 1600, ["model weights: one-time 2.4 GB download (needs HF_TOKEN),", "then cached in ~/.cache/huggingface"], anchor="left")
arrow([(1110, R1 + BH), (1110, EY)], both=True, dashed=True)
label(1110, 1580, ["text (Tamil word or feedback phrase)", "← mp3, only the first time each clip is rendered"])
arrow([(1930, R2 + BH), (1930, EY)], dashed=True)
label(1930, 1580, "invite e-mail (SMTP, TLS)")
arrow([(2160, 1735), (2240, 1735)], dashed=True)
label(2200, 1710, "delivered", f=F_SMALL)
arrow([(2470, EY), (2470, 1640), (2770, 1640), (2770, 140), (380, 140), (380, 160)], dashed=True)
label(1400, 140, "child opens the activation link  →  <PUBLIC_URL>/#/activate/<token>   (chooses a username and password → signed in as Child)")

# legend ----------------------------------------------------------------------------
lx, ly = 1400, EY
d.text((lx, ly), "Legend", font=F_H2, fill=BLACK)
d.line((lx, ly + 52, lx + 60, ly + 52), fill=BLACK, width=3); head((lx + 60, ly + 52), (lx, ly + 52))
d.text((lx + 72, ly + 40), "in-process call", font=F_BODY, fill=BLACK)
dash_line((lx, ly + 90), (lx + 60, ly + 90)); head((lx + 60, ly + 90), (lx, ly + 90))
d.text((lx + 72, ly + 78), "call to an external service", font=F_BODY, fill=BLACK)
d.line((lx, ly + 128, lx + 60, ly + 128), fill=BLACK, width=3); head((lx + 60, ly + 128), (lx, ly + 128)); head((lx, ly + 128), (lx + 60, ly + 128))
d.text((lx + 72, ly + 116), "both ends: request and response", font=F_BODY, fill=BLACK)

img.save(OUT, optimize=True)
print(OUT, img.size)
