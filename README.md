# Tamil Tutor

One application, two roles. A **child** signs in to practise Tamil: hear a
vowel, word or sentence spoken by a neural Tamil voice, say it, and be marked
by a local speech-recognition model — with a talking buddy character, daily
tasks, video lessons and a progress calendar. A **doctor** (speech therapist)
signs in on the same page, picks *Doctor*, and gets a dashboard: add students,
see each child's progress and deep-training queue, broadcast today's task with
a deadline, upload video lessons and see who watched them.

Both live in this one project and one server (FastAPI, port 8000); the role
chosen at sign-in decides which front end is shown, and every API route checks
the role of the session token (RBAC), so a child's token cannot reach the
doctor's endpoints and vice versa.

Recognition runs on [AI4Bharat IndicConformer](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual)
(600M, MIT licence), entirely locally: no API keys, no audio leaves the machine.
Pronunciation audio comes from Microsoft's neural Tamil voices and is cached,
so it needs the network only the first time each sound is rendered.

## Features

**For the child**

- **Speech practice** — hear a Tamil vowel, word or sentence in a neural
  voice (normal and slow), say it into the microphone, and get marked
  *correct / almost / try again* with stars, confetti and a spoken "well done"
- **52-item lesson list** — 12 vowels, 20 everyday words, 10 short and 10
  longer sentences, each with its Tamil script, English-letter form and meaning
- **Deep Training** — a word missed three times is rebuilt sound by sound:
  vowel → syllables → slow → full word, each step checked
- **Arcade Mode** — six speaking games (Say & Catch, Balloon Speech, Feed the
  Animal, Sound Match, Build the Word, Treasure Hunt), each climbing
  Words → Simple Sentences → Longer Sentences, with a star counter
- **Today's Task** — the item the doctor set, with a live countdown; a monthly
  calendar shows every day it was finished and the current streak
- **Video Lessons** — lessons recorded by the doctor, played in-app; how much
  was watched is reported back
- **Talking buddy** — an animated character that speaks the feedback
- **Transcribe** — upload or record any Tamil audio and get the text
- **Progress that follows the account** — best stars per item are kept on the
  server, so a child can switch devices
- Light / dark theme, works on phones and tablets

**For the doctor (speech therapist)**

- **Student accounts by invitation** — add a child with their details and
  photo; an activation link goes out by e-mail (or is shown to copy) and the
  child picks a username and password
- **Progress dashboard** — per child: stars and mastery per category, every
  item's best result and attempt count, the deep-training queue, recent
  attempts including arcade play
- **Daily tasks** — broadcast a vowel, word or sentence (or custom Tamil text)
  with a level and a deadline; see who finished, tried, or has not started
- **Video lessons** — upload recordings; see who watched each one and how far
- **Overview** — counts of students, open tasks, items mastered, lessons
  watched, and a live activity feed

**Under the hood**

- **Local speech recognition** — AI4Bharat IndicConformer 600M (RNNT
  decoding) on CPU; nothing is sent to a cloud service
- **Rule-based Tamil romanisation** and edit-distance scoring, with a
  containment guard so a word inside a longer utterance still counts
- **PostgreSQL** for accounts, attempts, tasks and lessons; files on disk for
  photos and videos
- **JWT sign-in with two roles** — a child's token cannot open the doctor's
  API and vice versa; sign-out and password changes retire tokens early
- **Neural text-to-speech** cached on disk, so pronunciations play instantly
  and work offline after the first render
- One FastAPI server, three plain-HTML pages, no build step; 288 automated tests

## Requirements

- **Python 3.11** — 3.12+ does not yet have wheels across this stack
- **PostgreSQL** for the accounts, progress, tasks and lessons — either Docker
  (`docker compose up -d`, see [Database](#database)) or a server of your own
- ~6 GB free disk for model weights (cached in `%USERPROFILE%\.cache\huggingface`)
- A GPU is optional; everything below is tuned for CPU

## Model access (required)

`ai4bharat/indic-conformer-600m-multilingual` is a **gated** repository. Nothing
will download until you do this once:

1. Sign in at <https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual>
   and accept the terms on the model page.
2. Create a **read** token at <https://huggingface.co/settings/tokens>.
3. Authenticate locally, any one of these:

Put it in `.env` at the project root (loaded automatically on startup):

```bash
HF_TOKEN=hf_your_read_token_here
```

or log in through the CLI:

```bash
.venv\Scripts\huggingface-cli.exe login
```

or set it in the shell, which overrides `.env`:

```bash
set HF_TOKEN=hf_your_read_token_here
```

`/health` reports `auth.hf_token_present` and which `.env` file was read, so you
can tell a missing token from a rejected one without digging through logs.

Until this is done, `/health` reports the reason and `/transcribe` returns 503
with the same message — the server stays up rather than crashing.

## Setup

```bash
py -3.11 -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Database

The doctor portal keeps accounts, progress, attempts, tasks and lesson
metadata in **PostgreSQL** (photos and video files stay on disk under
`data/`). The quickest way to have one is the container in
[docker-compose.yml](docker-compose.yml):

```bash
docker compose up -d
```

That starts `postgres:16` on port **5433** with the user, password and
database all named `tamiltutor`, which is exactly what `DATABASE_URL`
defaults to — so nothing needs to be configured. The data lives in the
`tamiltutor-pgdata` volume and survives restarts; `docker compose down`
stops the server and keeps it, `docker compose down -v` deletes it.

To use a PostgreSQL server of your own instead, create a database and a role
that owns it, then point `DATABASE_URL` at it in `.env`:

```bash
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME
```

The tables (and the `citext` extension, for case-insensitive e-mails and
usernames) are created on the first start; nothing has to be run by hand.

Have data in the old `data/portal.db` SQLite file? Copy it across once:

```bash
.venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py --replace
```

## Run the web app

```bash
.\run.ps1
```

Open <http://127.0.0.1:8000>. The sign-in page asks **"I am a: Child / Doctor"**
and then for the credentials of that role:

| Role | Signs in with | Lands on |
| --- | --- | --- |
| Child | username or e-mail + password (account created from the doctor's invite link) | the child app below |
| Doctor | e-mail + password (first account: `doctor@tamiltutor.local` / `doctor123`, see [Configuration](#configuration)) | the dashboard at `/doctor.html` |

The child app is a dashboard with a sidebar:

| Section | What it does |
| --- | --- |
| **Home** | Stars collected, items mastered, a "Continue" button that jumps to the next unmastered item, today's task with its countdown, and a month calendar (like LeetCode's) with a green circle on every day the daily task was finished, a streak count, and the time left for today |
| **Today's Task** | The item the doctor set for today, with a live timer to the deadline; practise it here and it is marked done |
| **Video Lessons** | Lessons the doctor recorded, one box each; tap one to play it in a near-full-window player. Watching is reported to the doctor |
| **Training** | Four boxes — Vowels, Words, Short Sentences, Simple Sentences. Open one to see every item as a tile; open a tile to practise it |
| **Deep Training** | Words missed three times in a row, rebuilt sound by sound — see below |
| **Arcade Mode** | Opens **Speech Adventure** (`/arcade.html`) in a new tab: six speaking games, each climbing Words → Simple Sentences → Longer Sentences — see [Arcade Mode](#arcade-mode-speech-adventure) |
| **Transcribe** | Upload a file or record from the microphone; get Tamil text with its English-letter form |
| **My Progress** | Every item with its best star rating, per category |
| **Settings** | Light / dark theme, buddy voice, reset progress |

The model status (green dot = ready to listen, amber = warming up, red = offline) sits in the top bar next to the theme button.

### Practising an item

Each item page has the word large, its romanisation, its meaning, and:

- **Pronounce** / **Slow** — hear it in a neural Tamil voice
- a big microphone — tap, say it, tap again
- **Check my pronunciation** — the model listens and marks it

A correct attempt earns three stars, with confetti and a chime; "almost there"
earns two; a miss earns one. Best stars are kept per item in the browser
(`localStorage`) *and* sent to the doctor portal, so progress follows the
child's account between devices and the doctor can see it. Three stars on an
item marks it mastered; category cards show a progress ring.

### Your buddy: Kili and friends

A 2D animated character sits in the corner of every page and reacts to what
the child does — and **says the verdict out loud**. Under **🎭 Character**
the child picks one of six buddies, each drawn as inline SVG and animated
with CSS (no images or libraries):

| | Name | |
| --- | --- | --- |
| 🦜 | **Kili** (கிளி) | a green parrot with a rainbow crest — the default |
| 🐶 | **Kutty** (குட்டி நாய்) | a cream puppy with floppy ears and a bell on its collar |
| 🐱 | **Poonai** (பூனை) | an orange kitten who wags her tail |
| 🧸 | **Karadi** (கரடி) | a brown teddy bear with a red bow |
| 🐘 | **Yaanai** (யானை) | a blue elephant whose ears flap and trunk lifts |
| 🤖 | **Robo** (ரோபோ) | a robot whose antenna light glows when you shine |

Every buddy has the same moods, driven by the stars of the attempt (body
movement only — no mouth animation, and the colours never change):

| Result | The buddy | Says (English or Tamil) |
| --- | --- | --- |
| ⭐⭐⭐ correct | big smile, **jumps** from bottom to top twice, then dances with sparkles | *"Well done! You spoke correctly."* |
| ⭐⭐ close | smiles, wiggles and waves | *"Almost! The correct pronunciation is …"* + the word, spoken slowly + *"Try once more!"* |
| ⭐ wrong | bends its head down, arms droop, frowns and sways | *"Your pronunciation is wrong. The correct pronunciation is …"* + the word + *"Say it slowly. You can do it!"* |
| silence | tilts its head, thinking | *"I could not hear you. Try again."* |

It also perks up while recording and looks thoughtful while the attempt is
checked. This happens in Training, Today's Task and every step of Deep
Training. Each verdict is spoken **once**; tapping the buddy only makes it
wiggle. The speech bubble shows the same words with the Tamil word and its
romanisation and has a ✕ to close it (the voice carries on). The 🔊 button
on the buddy mutes it; **Settings → your buddy** switches the voice between
English and Tamil.

The phrases are rendered once with the neural voices (`en-IN-Neerja`, and
the Tamil pronunciation voice) and cached under `cache/feedback/`, named by
a hash of the text so a reworded line is re-rendered; `/feedback` lists
them and `/feedback/{key}?lang=en|ta` serves the audio.

## Architecture

The whole system — both front ends, the API, the speech modules, storage and
the external services, with every data flow labelled — is drawn in
[docs/architecture.png](docs/architecture.png) (regenerate with
`py -3.11 docs\make_architecture.py`, needs Pillow).

## Roles, sign-in and access control

There is one sign-in page for both roles. `POST /api/auth/login` takes
`{role, identifier, password}`; the role decides which accounts are searched
(doctors by e-mail, children by username or e-mail), so a doctor's password
never opens the child app and vice versa. The response is a **JWT** (HS256,
signed with `JWT_SECRET`) sent back as a bearer token; its claims are the
account id (`sub`), the `role` (`doctor` or `student`), a token id (`jti`),
the account's `ver`, and `iat`/`exp` — it lasts `SESSION_DAYS` (7). Every
protected route goes through `require_doctor` or `require_student`, which
verify the signature and expiry and reject a token of the other role with 401.

Tokens are stateless — no session table is consulted on each request — but
two things retire one early:

- **Sign out** records the token's `jti` in `revoked_tokens` until it would
  have expired, so that token alone stops working; other devices stay in.
- **Changing the password** bumps the account's `token_version`; every token
  issued before it (its `ver` no longer matches) is refused, which signs all
  other devices out. The browser that made the change gets a fresh token in
  the response and stays signed in. Deleting a student has the same effect
  on the child's tokens, since the account they name is gone.

The **child front end** (`/`) keeps its token as `tamiltutor.token`; the
**doctor front end** (`/doctor.html`) keeps its own as
`tamiltutor.doctor.token`. Each page asks `/api/auth/me` on load and bounces
a token of the wrong role back to the sign-in page, so opening
`/doctor.html` as a child (or `/` as a doctor) simply returns you to sign-in.

Set `JWT_SECRET` in `.env` (any long random string; see
[Configuration](#configuration)). Without it the server makes one up at
each start, which works but signs everyone out whenever it restarts.

### Child accounts and invites

Children cannot register themselves. The doctor adds a student in the
dashboard (first name, last name, age, gender, e-mail, phone, address, optional
photo; **e-mail must be unique**), and the child receives an account-creation
link, `<PUBLIC_URL>/#/activate/<token>`, which opens this app's **Create my
account** screen — choose a username (the e-mail is pre-filled), a password
and its confirmation, and you are signed in. The link is single-use and expires
after `INVITE_DAYS` (7); until it is used the student card shows *Invite
pending* and the student page has **Resend invite**.

E-mail goes out over SMTP when `SMTP_HOST` and `SMTP_FROM` are set. **When it
is not configured nothing is lost:** the dashboard shows the activation link
with a Copy button so the doctor can share it by hand.

## What the doctor sees

| Section | What it does |
| --- | --- |
| **Dashboard** | Student count, open tasks with a countdown and how many have finished, video-lesson watch counts, a feed of recent attempts |
| **Students** | One card per child — photo, name, age, gender, e-mail, a mastery ring, whether the invite is pending. Add and delete from here |
| **Student page** | Profile, invite link, stars, mastered count, progress ring per category, every item with its best stars and attempts, the **deep-training** queue (locked words), today's task status, video lessons watched, recent attempts |
| **Today's Task** | Pick a vowel / word / short sentence / sentence — or type custom Tamil — choose the level (Easy / Medium / Hard, defaults from the kind), set the deadline (23:59 today by default) and broadcast it to every student; each open task shows who finished, tried, or has not started |
| **Video Lessons** | Upload a recorded lesson (MP4, WebM, OGV or MOV, up to `MAX_VIDEO_MB`); every student sees it at once; each lesson shows *N of M students finished watching*, who is part-way, who has not started; play back or delete |
| **Settings** | Change password, theme, this server's address and e-mail status |

### Today's task

The doctor broadcasts one item — a vowel, a word, a short sentence or a
sentence — with a deadline (23:59 that day unless set otherwise). It appears
in the sidebar with a badge and on the Home page with a countdown, and under
**Today's Task** with the full timer. Practising it uses the same recorder and
scoring as Training: two stars or better marks it done, the best result is
kept, and once the clock runs out it is shown as missed and can no longer be
submitted. Tasks on lesson-list items also count towards training stars.

### Video lessons

The doctor uploads pre-recorded lessons in the portal; each one appears here
as a box with a preview frame, its length and a *New* tag, and a badge in
the sidebar counts the ones still to watch. Tapping a box opens the lesson in
a player that fills nearly the whole window (Esc or ✕ closes it). While it
plays, the app tells the portal how far the child has got — every few
seconds and when the player closes — so the doctor sees *N of M students
finished watching*. Reaching 90% or the end marks it watched; a lesson
closed part-way shows its percentage and resumes from there next time. The
video itself streams from the portal with the child's session token in the
URL, since a `<video>` tag cannot send a bearer header.

What the doctor sees, per child: stars and mastered counts per category, every
item's best stars and attempts, which words are locked in deep training, task
completion, video lessons watched, and a feed of recent attempts. Every practice attempt is reported
to the portal in the background (`POST /api/student/attempts`); a word being
flagged for, or finishing, deep training is reported too.

The UI is a single `web/index.html` with no build step. It is hash-routed
(`#/train/words/w_amma`), so any screen can be bookmarked, and it collapses the
sidebar into a drawer below 820 px.

Recordings are converted to 16 kHz mono WAV in the browser before uploading,
so the server never needs ffmpeg to handle `webm/opus`.

The first request downloads the model and takes several minutes. `/health`
reports whether the weights are warm; the status pill in the sidebar reflects it.

## Command line

```bash
.venv\Scripts\python.exe scripts\transcribe_once.py samples\test_ta.wav
```

```bash
.venv\Scripts\python.exe scripts\transcribe_once.py audio.mp3 --segments
```

## HTTP API

| Endpoint | Method | Body | Returns |
| --- | --- | --- | --- |
| `/health` | GET | — | model id, revision, whether weights are loaded |
| `/transcribe` | POST | multipart `file` | Tamil text, `roman`, timings, segments |
| `/lexicon` | GET | — | 12 vowels, 20 words, 10 short and 10 longer sentences |
| `/romanize` | GET | `?text=…` | the English-letter form of any short Tamil text |
| `/practice` | POST | multipart `file`, `entry_id` | verdict, score, expected vs heard |
| `/pronounce/{id}` | GET | `?speed=normal\|slow` | MP3 of that entry, cached |
| `/decompose/{id}` | GET | — | deep-training steps for an entry |
| `/say` | GET | `?text=…&speed=` | MP3 of any short Tamil text, cached by content |
| `/check` | POST | multipart `file`, `text`, optional `lenient` | verdict against arbitrary text |
| `/arcade/pick` | POST | multipart `file`, `target` (entry id), `options` (JSON list of entry ids) | one recording judged against every option: `picked` (best match), `correct`, per-option verdicts |
| `/speak` | POST | form `text`, optional `speed` | MP3 of arbitrary Tamil text |

```bash
curl -F "file=@samples/test_ta.wav" http://127.0.0.1:8000/transcribe
```

```json
{
  "text": "இந்த விதிகள் திருத்தப்படுவதற்கு முன்னர்",
  "roman": "intha vithigal thiruthappaduvatharku munnar",
  "language": "ta",
  "decoding": "rnnt",
  "duration_sec": 12.4,
  "elapsed_sec": 3.2,
  "real_time_factor": 0.26,
  "segments": [{ "start_sec": 0.0, "end_sec": 12.4, "text": "…", "roman": "…" }]
}
```

`real_time_factor` is compute seconds per audio second. Below 1.0 is faster
than real time.

### Accounts, tasks and lessons (`/api/…`, JSON, `Authorization: Bearer <token>`)

**Public**

| Endpoint | Method | Body | Returns |
| --- | --- | --- | --- |
| `/api/auth/login` | POST | `{role: doctor\|child, identifier, password}` | `{token, role, doctor\|student}` |
| `/api/auth/me` | GET | — | the role and account behind a token |
| `/api/auth/logout` | POST | — | ends the session |
| `/api/auth/doctor/login`, `/api/auth/student/login` | POST | per-role forms of the above | |
| `/api/invites/{token}` | GET | — | whether an invite is valid, the child's name and e-mail |
| `/api/invites/{token}/activate` | POST | `{username, password, confirm_password}` | `{token, student}` — signed in |
| `/api/lexicon` | GET | — | the lesson list grouped by category, with levels |

**Doctor role**

| Endpoint | Method | Body | Returns |
| --- | --- | --- | --- |
| `/api/doctor/me` · `/api/doctor/password` | GET · POST | — · `{current_password, new_password}` | |
| `/api/doctor/overview` | GET | — | counts, open tasks, recent activity, students |
| `/api/doctor/students` | GET · POST | multipart `first_name last_name age gender email phone address [photo]` | students · `{student, invite}` |
| `/api/doctor/students/{id}` | GET · DELETE | — | full progress, tasks, videos, attempts · remove |
| `/api/doctor/students/{id}/invite` · `/photo` | POST | — · multipart `photo` | new invite link · updated student |
| `/api/doctor/tasks` | GET · POST | `{kind, entry_id \| text, level?, roman?, meaning?, note?, due_at}` | tasks with every student's result · the task |
| `/api/doctor/tasks/{id}` | GET · DELETE | — | one task · remove it |
| `/api/doctor/videos` | GET · POST | multipart `title description [duration] file` | lessons with watch status per student · the lesson |
| `/api/doctor/videos/{id}` | GET · DELETE | — | one lesson · remove it and its file |

**Child role**

| Endpoint | Method | Body | Returns |
| --- | --- | --- | --- |
| `/api/student/me` | GET | — | profile |
| `/api/student/progress` | GET | — | best stars per item, deep-training states |
| `/api/student/progress/sync` | POST | `{items, deep}` | merged progress (best-of) |
| `/api/student/attempts` | POST | `{entry_id, category, verdict, score_percent, source}` | the updated item |
| `/api/student/deep/{entry_id}` | PUT | `{status, wrong, step}` | — |
| `/api/student/tasks` · `/api/student/tasks/{id}/attempts` | GET · POST | — · `{verdict, score_percent}` | today's tasks · updated status |
| `/api/student/videos` · `/api/student/videos/{id}/progress` | GET · POST | — · `{position, duration?, ended?}` | lessons · updated status |
| `/api/student/calendar` | GET | — | every task with the child's result |
| `/photos/{name}` · `/videos/{name}?t=<token>` | GET | — | student photo · lesson video (any valid JWT of either role; Range supported) |

Passwords are PBKDF2-SHA256 hashes (never stored in clear); tokens are JWTs
that expire after `SESSION_DAYS` (7) — see [Roles, sign-in and access
control](#roles-sign-in-and-access-control).

## Only the most accurate decoding

The checkpoint supports two decoding modes. Measured over 25 FLEURS Tamil
clips, RNNT wins on both metrics:

| | WER | CER | real-time factor |
| --- | --- | --- | --- |
| CTC | 0.1858 | 0.0464 | 0.17 |
| **RNNT** | **0.1641** | **0.0454** | 0.36 |

RNNT costs about 2.1× the compute and still runs roughly 3× faster than real
time on CPU, so accuracy wins and **the choice is not exposed** — no dropdown,
no request parameter, no environment variable. A configurable setting only
created a way for a stale `.env` to silently downgrade accuracy.

CTC is still reachable from [scripts/eval_wer.py](scripts/eval_wer.py), which
is how the two were compared; re-run it on your own audio if you want to check
the conclusion holds there.

Measured end to end against the running server: **WER 0.126, CER 0.026.**

## Pronunciation practice

Pick from the dropdown — 12 Tamil vowels, 20 everyday words, 10 short sentences
(2–3 words) or 10 longer ones (4–5 words) — record yourself saying it, and
submit. You get back the Tamil the model heard, its
English-letter form, and a verdict.

Every transcript carries a `roman` field alongside the Tamil, produced by
[src/translit.py](src/translit.py).

| Verdict | Meaning |
| --- | --- |
| **Correct** | Exact match, or ≥ 85% similar |
| **Almost there** | 55–85% similar — right shape, wrong detail |
| **Not quite** | Below 55% |
| **Nothing heard** | Silence, or nothing recognisable |

Scoring compares the Tamil script and the romanisation, and takes the better of
the two, so a correct pronunciation is not failed because the model chose a
homophonous spelling. Two guards stop a wrong answer sneaking through: a target
of fewer than three characters cannot be matched by containment (a bare vowel
occurs inside most Tamil words), and a target buried inside a much longer
transcript does not count.

Long versus short vowels (அ/ஆ, இ/ஈ, எ/ஏ) are deliberately failed — that
distinction is the point of the drill.

### A caveat worth knowing

IndicConformer is trained on continuous speech, not isolated phonemes. Single
vowels are the hardest case for it and will sometimes come back wrong or empty
even when you say them correctly. Whole words are considerably more reliable,
and sentences are the most reliable of all: every one of the twenty, short and
long, at both speeds, is recognised word-for-word from its own pronunciation
clip. Say the sound clearly and hold it for about a second.

Pure digital silence used to make the model hallucinate a word; clips below the
audible floor are now answered directly as "no speech" without invoking it.

## English letters (romanisation)

Every Tamil transcript comes back with an English-letter form beside it. This
is spelling, not translation: பால் becomes `paal`, not "milk".

A letter-for-letter table is not good enough, because Tamil writes one symbol
for sounds English spells differently depending on position. The transliterator
applies the context rules a Tamil speaker uses:

| Rule | Example |
| --- | --- |
| Plosives voice between vowels | மகன் → `magan`, வீடு → `veedu` |
| …but stay hard initially and when doubled | கை → `kai`, அக்கா → `akka` |
| Nasal clusters merge | தங்கை → `thangai` (not *thangkai*) |
| | தம்பி → `thambi`, நண்பன் → `nanban` |
| ச is `s`, except doubled | சமையல் → `samaiyal`, but பச்சை → `pachai` |
| Doubling depends on reading length | ட்ட → `tt`, but த்த collapses: தாத்தா → `thaatha` |
| ற்ற is written `tr` | காற்றில் → `kaatril` |
| Final ஆ softens | அம்மா → `amma` (not *ammaa*) |
| Final ய் reads as a vowel | நாய் → `naai` |

All twelve vowels stay distinct (`a/aa`, `i/ee`, `u/oo`, `e/ae`, `o/oa`), so
the practice drill can still tell long from short.

The invariant that keeps this honest: **every one of the 20 lexicon words
romanises to exactly its conventional spelling**, and a test asserts it. Change
a rule and break a real word, and the suite fails.

## Audio formats

Anything is downmixed to mono and resampled to 16 kHz automatically. Decoding
falls through three tiers, first match wins:

| Tier | Handles |
| --- | --- |
| libsndfile (`soundfile`, `librosa`) | WAV, FLAC, MP3, OGG/Vorbis, AIFF, CAF, W64 |
| PyAV (`av`) | **M4A/AAC**, MP4, WebM/Opus, WMA, AMR, 3GP |
| system `ffmpeg`, if on PATH | anything left over |

**M4A needs no extra setup.** libsndfile cannot read AAC in an MP4 container, so
those files go to PyAV, whose wheel bundles the ffmpeg libraries — installing
`ffmpeg` separately is not required. The third tier exists only as a safety net.

A file that no tier can decode returns 422 with the list of supported formats,
and is rejected before the model is touched.

## Long audio

Files longer than 30 seconds are split before decoding, because attention cost
grows quadratically with length. Splits are placed at silences where possible
so words are not cut in half; a stretch of continuous speech longer than the
chunk limit is hard-split with a 2-second overlap. Per-chunk text and timings
come back in `segments`.

## Evaluation

Build a JSONL manifest of clips with known transcripts:

```json
{"audio": "eval/001.wav", "text": "நான் தமிழ் பேசுகிறேன்"}
```

```bash
.venv\Scripts\python.exe scripts\eval_wer.py data\eval.jsonl --decoding ctc --out results\ctc.jsonl
```

Reports corpus WER and CER. **Watch CER more than WER for Tamil** — the
language is agglutinative, so one wrong suffix destroys a whole "word" in the
WER count while the transcript stays perfectly readable.

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```

These run against a stub model and need no downloads, but they **need the
PostgreSQL server running** (`docker compose up -d`): the account, task and
lesson tests (`tests/test_portal_*.py`) use a separate `tamiltutor_test`
database — created on the first run, emptied before every test — and send no
e-mail. The run stops with a clear message if the server is not reachable. To
include a real end-to-end pass, put a clip at `samples/test_ta.wav` and set
`RUN_MODEL_TESTS=1`.

## Configuration

All settings are environment variables (see [src/config.py](src/config.py)). A
`.env` file at the project root is loaded on startup; real environment variables
take precedence over it. Copy [.env.example](.env.example) to get started —
`.env` is gitignored, so your token stays out of the repository.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ASR_MODEL_ID` | `ai4bharat/indic-conformer-600m-multilingual` | model to load |
| `ASR_REVISION` | `main` | pin to a commit sha to freeze the remote code |
| `ASR_LANGUAGE` | `ta` | any of the model's 22 languages |
| `ASR_EAGER_LOAD` | `1` | load weights at startup instead of first request |
| `HF_TOKEN` | — | Hugging Face read token; required, the repo is gated |
| `CHUNK_SEC` | `30` | chunk length for long audio |
| `CHUNK_OVERLAP_SEC` | `2` | overlap when hard-splitting continuous speech |
| `MAX_UPLOAD_MB` | `200` | upload size limit |
| `MAX_DURATION_SEC` | `3600` | audio duration limit |
| `MAX_CONCURRENCY` | `1` | simultaneous transcriptions |
| `TORCH_THREADS` | torch default | CPU threads for inference |
| `TTS_VOICE` | `ta-IN-PallaviNeural` | neural voice for Pronounce; or `ta-IN-ValluvarNeural` |
| `TTS_WARM_CACHE` | `1` | render all 64 pronunciation clips at startup |
| `PUBLIC_URL` | `http://127.0.0.1:8000` | this server as a browser reaches it — the address in invite links |
| `DOCTOR_NAME` / `DOCTOR_EMAIL` / `DOCTOR_PASSWORD` | `Dr. Tamil Tutor` / `doctor@tamiltutor.local` / `doctor123` | the first doctor account, created once; more doctors or a reset: `scripts\create_doctor.py "Dr. Priya" priya@clinic.org` |
| `DATABASE_URL` | `postgresql://tamiltutor:tamiltutor@127.0.0.1:5433/tamiltutor` | the PostgreSQL database (the docker-compose one by default) |
| `DB_POOL_SIZE` | `5` | connections kept open to it |
| `TEST_DATABASE_URL` | `DATABASE_URL` with the name `tamiltutor_test` | the database the tests empty and use |
| `JWT_SECRET` | — (random per start) | signs the sign-in tokens; **set it**: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SESSION_DAYS` / `INVITE_DAYS` | `7` / `7` | how long a sign-in token / an activation link lasts |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS`, `SMTP_SSL` | — | invite e-mail; unset = links are shown to copy |
| `MAX_PHOTO_MB` / `MAX_VIDEO_MB` | `5` / `500` | upload limits |
| `PORTAL_DATA_DIR` | `data/` | where photos and videos are kept |

### Security note

The model is loaded with `trust_remote_code=True`, which executes code from the
Hugging Face Hub. `ASR_REVISION` defaults to `main`; set it to a specific commit
sha in any deployment so an upstream change cannot alter behaviour underneath
you. Known-good revision at the time of writing:

```bash
set ASR_REVISION=e9b71b369c048e2c6b634d4c131061c34e441179
```

## Deep Training

A word a child gets wrong **three times in a row** in Training is flagged:
its tile greys out with "Deep training required", and it appears in the
**Deep Training** section (the sidebar shows a count). Tapping it starts a
step-by-step drill that rebuilds the word from its sounds:

```
அம்மா   →   அ  ·  அம்  ·  மா  ·  அம்மா (slowly)  ·  அம்மா
வீடு    →   ஈ  ·  வீ   ·  டு  ·  வீடு (slowly)   ·  வீடு
```

First the vowel of the first syllable on its own, then each syllable, then the
whole word slowly, then at normal speed. Sentences split into words, with a
build-up of the first two, three… words before the whole thing. Every step is
pronounced by the neural voice (pieces are rendered and cached the moment a
word is flagged), and the child records and is checked on each one.

The split is rule-based ([src/decompose.py](src/decompose.py)): Tamil script
carries the vowel on the consonant, and a consonant with a virama (புள்ளி) has
no vowel, so it always closes the syllable before it — ம் never stands alone.

### How the steps are gated — and why

| Step | Passes on | After 3 misses |
| --- | --- | --- |
| pieces, words, build-ups | correct **or** close | "Good try — move on" appears |
| whole word, slowly and at normal speed | correct only | never skipped |

The scaffold steps are checked leniently and can be moved past because the
recogniser, not the child, is the unreliable part there: it is a
continuous-speech model and often hears nothing at all for a lone vowel, even
from a perfect recording. The whole-word steps are where it is reliable, so
they are the real gate. A child cannot finish deep training without saying the
whole word correctly.

Finishing marks the word **deep-trained**, resets its miss count, and unlocks
it in Training. "Practise again later" always leads back out without losing
the drill's place.

Endpoints behind it: `GET /decompose/{id}` (the steps), `GET /say?text=…`
(any short Tamil, cached by content), `POST /check` (score a recording against
arbitrary text, with a `lenient` flag).

## Hearing the pronunciation

Every entry in the practice tab has **Pronounce** and **Slow** buttons that play
it in a native-quality neural Tamil voice — the same class of voice as Google's
pronunciation feature. Slow renders the word at 65 % speed so each sound can be
heard separately.

Audio comes from Microsoft's neural voices via `edge-tts`. Two voices are
offered; set `TTS_VOICE` to pick:

| Voice | |
| --- | --- |
| `ta-IN-PallaviNeural` | female, the default |
| `ta-IN-ValluvarNeural` | male |

**Every entry is rendered once and cached** under `cache/pronounce/` — all 104
clips (52 entries × 2 speeds) are generated in the background at startup, so
the first click is instant and the feature works offline afterwards. `/health`
reports `pronunciation.ready / total`. Synthesis itself needs an internet
connection; if it is unavailable and the entry is not cached, the browser falls
back to any Tamil voice installed on the machine, and says so.

### Verified clear

To check the voice is actually intelligible rather than merely present, every
cached clip was played back into the recogniser through `/practice`. **All 13
multi-syllable words came back word-for-word correct.** Isolated vowels and
one-syllable words mostly did not — and that is the recogniser, not the voice:
padding, repeating, or slowing the same audio does not help, because a
continuous-speech model has no notion of a lone phoneme. It is the same
limitation the practice drill itself has on single vowels.

`POST /speak` with a `text` field synthesises arbitrary Tamil (not cached).

## Arcade Mode: Speech Adventure

**Arcade Mode** in the child's sidebar opens `/arcade.html` in a new tab — a
separate, game-styled page ("Speech Adventure — Say · Learn · Grow") that
shares the child's sign-in and shows their name, photo and star total. Six games,
laid out as six cards:

| Game | How it is played |
| --- | --- |
| ⭐ **Say & Catch** | A star carries the item; say it and the star flies into the child's hands |
| 🎈 **Balloon Speech** | Several balloons, each with an item; say the target one. The balloon that *heard* you pops — so a wrong answer pops the wrong balloon and shows what was said |
| 🐾 **Feed the Animal** | An animal asks for the item; say it correctly and the food flies into its mouth |
| 🎧 **Sound Match** | The item is played but not shown; choose it from the options, then say it for a bonus |
| 🧩 **Build the Word** | The item is split into pieces (syllables for a word, words for a sentence); say each piece to snap it onto the sign, then the whole thing |
| 🧭 **Treasure Hunt** | Five stepping stones, one item each; every correct one moves the explorer forward, the last opens the chest |

Every game climbs the same three **levels, in order: Words → Simple Sentences →
Longer Sentences** (the lexicon's 20 words, 10 short and 10 long sentences).
A level is five rounds; finishing it opens the next one for that game. Each
correct round is one star, shown on the **My Stars** counter and kept per child
in the browser (`tamiltutor.arcade.<id>`). Every attempt is also reported to the
doctor's portal as an attempt with `source: "arcade"`, so words said correctly
in a game count as progress on those words.

Every game judges speech with the same recogniser and scoring as Training:
`POST /practice` for a whole item, `POST /check` (lenient) for a piece in Build
the Word, and `POST /arcade/pick` for Balloon Speech — one recording judged
against every balloon on screen, which returns the best match (`picked`) as well
as the verdict for the target. Listen / Slow buttons play the neural voice;
"Well done!" feedback is spoken through `/feedback/…` and can be turned off
under ⚙️, along with the sound effects. Like the other pages it is plain HTML
with no build step; open `/arcade.html?debug` to get `window.__arcade`
(`clip(blob, name)` feeds a recording in as if the microphone had produced it).

## Layout

```
src/       config.py  audio.py  asr.py  api.py  tts.py  pronounce.py  feedback.py
           translit.py   Tamil -> Latin romanisation
           lexicon.py    the vowels, words and sentences to practise
           scoring.py    judging an attempt against a target
           decompose.py  deep-training steps
           portal/       the doctor side, mounted into the same app
             api.py      /api/* routes (JWT auth with roles, students, tasks, videos)
             db.py       PostgreSQL schema and connection pool   security.py  password hashing, JWTs
             mailer.py   invite e-mail                           lexicon.py   lesson list for the dashboard
web/       index.html    the sign-in page and the child app (single page, no build step)
           arcade.html   Arcade Mode: the six Speech Adventure games
           doctor.html   the doctor's dashboard
data/      photos/  videos/   (created on first start; not in git)
docker-compose.yml       the PostgreSQL container
docs/      architecture.png  make_architecture.py  module_architecture.png  make_module_diagram.py
scripts/   transcribe_once.py  eval_wer.py  create_doctor.py  migrate_sqlite_to_postgres.py
tests/     test_api.py  test_portal_auth.py  test_portal_students.py
           test_portal_progress_tasks.py  test_portal_videos.py  ...
```

## Troubleshooting

**`/health` says "gated repository".** You have not accepted the model terms or
authenticated. See [Model access](#model-access-required) above.

**Install fails on Python 3.13.** Use 3.11. This is the single most common cause
of a broken setup here.

**`onnxruntime-gpu` fails to load.** Install plain `onnxruntime` unless you have
CUDA, despite what the model card lists.

**Transcription is very slow.** Expect roughly 1–3× real time for CTC on CPU.
Try `TORCH_THREADS` matched to your physical core count. If it is still too
slow, move to `faster-whisper` with an int8 Tamil model rather than tuning the
Conformer.

**An uploaded file will not decode.** The server tries libsndfile, then PyAV,
then a system ffmpeg. M4A, MP4 and WebM are covered by PyAV with no extra
install — if one of those fails, check `av` is installed. Installing ffmpeg and
putting it on `PATH` covers the remaining exotic formats.
