"""Measure WER and CER against a reference set.

The manifest is JSON Lines, one object per clip::

    {"audio": "samples/eval/001.wav", "text": "தமிழ் உரை"}

Relative audio paths resolve against the manifest's own directory.

    python scripts/eval_wer.py data/eval.jsonl --decoding ctc

For Tamil, watch CER more closely than WER: the language is agglutinative, so a
single wrong suffix ruins a whole "word" while the output stays readable.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.asr import TamilASR  # noqa: E402
from src.audio import AudioError  # noqa: E402

# Punctuation that neither model nor reference should be judged on.
_PUNCT = set(".,!?;:‘’“”'\"()[]{}–—-।॥")


def normalize(text: str) -> str:
    """NFC-normalise, drop punctuation, collapse whitespace, lowercase Latin."""
    text = unicodedata.normalize("NFC", text)
    text = "".join(" " if ch in _PUNCT else ch for ch in text)
    return " ".join(text.split()).lower()


def load_manifest(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSON — {exc}") from exc
        if "audio" not in row or "text" not in row:
            raise SystemExit(f"{path}:{line_no}: needs both 'audio' and 'text'")
        audio = Path(row["audio"])
        row["audio"] = audio if audio.is_absolute() else path.parent / audio
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Tamil ASR accuracy.")
    parser.add_argument("manifest", type=Path, help="JSONL manifest")
    parser.add_argument("--decoding", choices=["ctc", "rnnt"], default="ctc")
    parser.add_argument("--limit", type=int, default=0, help="only the first N clips")
    parser.add_argument("--out", type=Path, help="write per-clip results as JSONL")
    args = parser.parse_args()

    try:
        import jiwer
    except ImportError:
        raise SystemExit("jiwer is required: pip install jiwer")

    rows = load_manifest(args.manifest)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("manifest is empty")

    asr = TamilASR(decoding=args.decoding)
    asr.load()

    refs: list[str] = []
    hyps: list[str] = []
    details: list[dict] = []
    audio_sec = compute_sec = 0.0

    for i, row in enumerate(rows, 1):
        try:
            result = asr.transcribe(row["audio"], decoding=args.decoding)
        except (AudioError, FileNotFoundError) as exc:
            print(f"  [{i}/{len(rows)}] skipped {row['audio']}: {exc}", file=sys.stderr)
            continue

        ref, hyp = normalize(row["text"]), normalize(result.text)
        if not ref:
            print(f"  [{i}/{len(rows)}] skipped: empty reference", file=sys.stderr)
            continue

        refs.append(ref)
        hyps.append(hyp)
        audio_sec += result.duration_sec
        compute_sec += result.elapsed_sec
        details.append(
            {
                "audio": str(row["audio"]),
                "reference": ref,
                "hypothesis": hyp,
                "wer": jiwer.wer(ref, hyp),
                "cer": jiwer.cer(ref, hyp),
            }
        )
        print(
            f"  [{i}/{len(rows)}] WER {details[-1]['wer']:.3f}  CER {details[-1]['cer']:.3f}",
            file=sys.stderr,
        )

    if not refs:
        raise SystemExit("nothing could be evaluated")

    corpus_wer = jiwer.wer(refs, hyps)
    corpus_cer = jiwer.cer(refs, hyps)

    print("\n" + "=" * 46)
    print(f"clips evaluated : {len(refs)}")
    print(f"decoding        : {args.decoding}")
    print(f"corpus WER      : {corpus_wer:.4f}")
    print(f"corpus CER      : {corpus_cer:.4f}")
    print(f"audio           : {audio_sec / 60:.1f} min")
    print(f"compute         : {compute_sec / 60:.1f} min")
    print(f"real-time factor: {compute_sec / audio_sec:.2f}x" if audio_sec else "")
    print("=" * 46)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            for row in details:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"per-clip results written to {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
