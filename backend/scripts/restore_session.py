"""Restore a session ZIP offline; destination must not exist."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.session_restore import restore_session

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path, help="NEW SQLite file, never a production database")
    args = parser.parse_args()
    print(json.dumps(restore_session(args.archive, args.destination)))
