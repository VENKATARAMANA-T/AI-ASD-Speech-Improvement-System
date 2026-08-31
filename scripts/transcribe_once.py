"""Transcribe a single audio file from the command line.

    python scripts/transcribe_once.py samples/test_ta.wav
    python scripts/transcribe_once.py audio.mp3 --decoding rnnt --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows consoles default to cp1252, which cannot encode Tamil at all: printing
# a transcript would raise UnicodeEncodeError instead of showing the result.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from src.asr import DEFAULT_DECODING, ModelAccessError, TamilASR  # noqa: E402
from src.audio import AudioError  # noqa: E402
from src.config import settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe Tamil audio.")
    parser.add_argument("audio", type=Path, help="path to an audio file")
    parser.add_argument(
        "--decoding",
        choices=["ctc", "rnnt"],
        default=DEFAULT_DECODING,
        help="the app always uses %(default)s, the more accurate mode; ctc is "
        "here only for comparison",
    )
    parser.add_argument("--language", default=settings.asr_language)
    parser.add_argument("--json", action="store_true", help="emit the full result as JSON")
    parser.add_argument("--segments", action="store_true", help="print per-chunk output")
    args = parser.parse_args()

    asr = TamilASR(language=args.language, decoding=args.decoding)
    # Plain ASCII: Windows consoles default to cp1252 and mangle typography.
    print(f"loading {asr.model_id} ... (first run downloads several GB)", file=sys.stderr)

    try:
        result = asr.transcribe(args.audio, decoding=args.decoding)
    except AudioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ModelAccessError as exc:
        # Actionable on its own; a traceback would only bury the instructions.
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.segments:
        for seg in result.segments:
            print(f"[{seg.start_sec:7.2f} - {seg.end_sec:7.2f}]  {seg.text}")
        print()

    print(result.text or "(no speech detected)")
    print(
        f"\n{result.duration_sec:.1f}s audio · {result.elapsed_sec:.1f}s compute · "
        f"RTF {result.real_time_factor:.2f}x · {result.decoding}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
