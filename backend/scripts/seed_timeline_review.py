"""Create an isolated synthetic review fixture; never target a user's archive."""
import os
from pathlib import Path
import sys
import tempfile

import cv2
import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from app.config import Mode, Settings
from app.main import create_app
from test_feedback import seed, end_hand
from test_decision_frames import store_event

path = Path(tempfile.mkdtemp(prefix="zeros-timeline-")) / "hands.sqlite3"
os.environ["HAND_DB_PATH"] = str(path)
with TestClient(create_app(Settings(mode=Mode.TRAINING))) as client:
    data = seed(client, mode=Mode.TRAINING)
    store, frozen, *_ = data
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(image, "Synthetic decision frame 100", (20, 180), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
    ok, jpeg = cv2.imencode(".jpg", image)
    assert ok
    store.save_decision(frozen.record(), store_event(store, frozen), jpeg.tobytes())
    end_hand(data)
print(path)

if "--serve" in sys.argv:
    import uvicorn
    uvicorn.run(create_app(Settings(mode=Mode.TRAINING)), host="0.0.0.0", port=8000)
