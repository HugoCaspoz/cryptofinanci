"""Replay an exported event JSON without loading video, OCR or strategy."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.event_engine.models import EventBatch
from app.event_engine.replay import replay_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        batch = EventBatch.model_validate_json(args.file.read_text(encoding="utf-8-sig"))
        replay = replay_batch(batch)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"No se puede reproducir el historial: {exc}\n")
    print(json.dumps({"sequence": replay.sequence, "history_truncated": batch.gap,
                      "checkpoint_sequence": batch.checkpoint.sequence,
                      "state": asdict(replay.state)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
