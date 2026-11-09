import os
from datetime import datetime
from pathlib import Path

import piexif
import pytest
from PIL import Image

from photosorter.db.schema import connect


def make_jpeg(path: Path, color=(120, 80, 40), exif_date: str | None = None, mtime: datetime | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (64, 48), color)
    if exif_date:
        exif = piexif.dump({"Exif": {piexif.ExifIFD.DateTimeOriginal: exif_date.encode()}})
        img.save(path, "JPEG", exif=exif)
    else:
        img.save(path, "JPEG")
    if mtime:
        ts = mtime.timestamp()
        os.utime(path, (ts, ts))
    return path


class StubDetector:
    """Treats files whose name contains 'person' as having 2 people."""

    def count_people(self, path: Path) -> int:
        return 2 if "person" in path.name else 0


@pytest.fixture
def conn():
    c = connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "photos"
    make_jpeg(root / "a" / "person_dated.jpg", (200, 10, 10), exif_date="2024:06:15 12:00:00")
    make_jpeg(root / "b" / "person_20230704_101500.jpg", (10, 200, 10))
    make_jpeg(root / "person_mtime.jpg", (10, 10, 200), mtime=datetime(2021, 3, 2, 9, 0, 0))
    make_jpeg(root / "c" / "person_dup.jpg", (50, 50, 50), exif_date="2024:06:20 08:00:00")
    make_jpeg(root / "d" / "person_dup.jpg", (60, 60, 60), exif_date="2024:06:20 09:00:00")
    make_jpeg(root / "landscape.jpg", (0, 150, 150), exif_date="2024:06:15 13:00:00")
    return root
