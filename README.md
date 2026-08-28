# AI ASD Speech Improvement System

Tamil speech practice for children, with a dashboard for the speech
therapist. Speech recognition runs locally on the AI4Bharat IndicConformer
model, so no audio leaves the machine.

## Setup

Python 3.11 is required.

```bash
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The model repository is gated: accept its terms on Hugging Face and put a
read token in `.env` as `HF_TOKEN=...` (see `.env.example`).

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```
