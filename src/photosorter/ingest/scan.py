import hashlib
from datetime import datetime
from pathlib import Path

from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 0x9003
_DATETIME = 0x0132


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_exif_date(path: Path) -> str | None:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            value = exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
    except Exception:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    return value or None


def iter_images(root: Path, skip_dirs: list[str] | None = None):
    skip = set(skip_dirs or [])
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if any(part in skip for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


def scan(conn, root: Path, skip_dirs: list[str] | None = None) -> int:
    """Hash every image under root and record it. Originals are only read."""
    count = 0
    for path in iter_images(root, skip_dirs):
        stat = path.stat()
        conn.execute(
            "INSERT OR REPLACE INTO photos (sha256, path, size, format, exif_date, mtime) VALUES (?,?,?,?,?,?)",
            (
                sha256_file(path),
                str(path),
                stat.st_size,
                path.suffix.lower().lstrip("."),
                read_exif_date(path),
                datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
            ),
        )
        count += 1
    conn.commit()
    return count
