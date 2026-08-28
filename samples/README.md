# Sample audio

Audio files here are ignored by git. Drop a short Tamil clip in as
`test_ta.wav` to use the quick-start commands and the optional end-to-end model
test.

Requirements: any format the server can decode; it is downmixed to mono and
resampled to 16 kHz automatically. 5–15 seconds is a good size for a first run.

Sources for Tamil test audio:

- Mozilla Common Voice, Tamil (`ta`) — <https://commonvoice.mozilla.org/ta/datasets>
- AI4Bharat IndicVoices — <https://ai4bharat.iitm.ac.in/datasets>
- Or record yourself through the web UI at <http://127.0.0.1:8000> and save the
  clip from the player.

For evaluation, build a JSONL manifest and point `scripts/eval_wer.py` at it:

```json
{"audio": "eval/001.wav", "text": "நான் தமிழ் பேசுகிறேன்"}
```
