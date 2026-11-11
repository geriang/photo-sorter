from pathlib import Path
from typing import Protocol


class FaceDetector(Protocol):
    def count_people(self, path: Path) -> int: ...


class InsightFaceDetector:
    """Local face detection. Requires the optional `faces` extra and a one-off model download."""

    def __init__(self, det_size: tuple[int, int] = (640, 640)):
        from insightface.app import FaceAnalysis

        self._app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=-1, det_size=det_size)

    def count_people(self, path: Path) -> int:
        import numpy as np
        from PIL import Image

        with Image.open(path) as img:
            arr = np.array(img.convert("RGB"))[:, :, ::-1]
        return len(self._app.get(arr))


def detect_people(conn, detector: FaceDetector) -> int:
    rows = conn.execute("SELECT sha256, path FROM photos WHERE has_people IS NULL").fetchall()
    for row in rows:
        n = detector.count_people(Path(row["path"]))
        conn.execute(
            "UPDATE photos SET has_people = ?, group_size = ? WHERE sha256 = ?",
            (1 if n > 0 else 0, n, row["sha256"]),
        )
    conn.commit()
    return len(rows)
