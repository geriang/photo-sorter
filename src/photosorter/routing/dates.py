import re
from datetime import datetime, timezone

MIN_YEAR = 1990

_FILENAME_PATTERNS = [
    re.compile(r"(?<!\d)(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})[-_. T]?(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})(?:\d{3})?(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)"),
]


def _build(parts: tuple[int, ...], now: datetime) -> datetime | None:
    try:
        dt = datetime(*parts)
    except ValueError:
        return None
    if dt.year < MIN_YEAR or dt.year > now.year + 1:
        return None
    return dt


def parse_exif_date(value: str | None, now: datetime | None = None) -> datetime | None:
    if not value:
        return None
    now = now or datetime.now()
    m = re.match(r"^\s*(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", value)
    if not m:
        return None
    return _build(tuple(int(g) for g in m.groups()), now)


def parse_filename_date(filename: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now()
    for pattern in _FILENAME_PATTERNS:
        for m in pattern.finditer(filename):
            parts = tuple(int(g) for g in m.groups())
            if len(parts) == 3:
                parts = parts + (0, 0, 0)
            dt = _build(parts, now)
            if dt:
                return dt
    return None


def resolve_date(
    exif_date: str | None,
    filename: str,
    mtime: float | None,
    now: datetime | None = None,
) -> tuple[datetime | None, str]:
    """Return (date, source). Order: exif, filename, mtime, none."""
    now = now or datetime.now()
    dt = parse_exif_date(exif_date, now)
    if dt:
        return dt, "exif"
    dt = parse_filename_date(filename, now)
    if dt:
        return dt, "filename"
    if mtime is not None:
        dt = _build(
            (lambda t: (t.year, t.month, t.day, t.hour, t.minute, t.second))(
                datetime.fromtimestamp(mtime, tz=timezone.utc).replace(tzinfo=None)
            ),
            now,
        )
        if dt:
            return dt, "mtime"
    return None, "none"


def folder_for(dt: datetime | None) -> str:
    if dt is None:
        return "Undated"
    return f"{dt.year:04d}/{dt.month:02d}"
