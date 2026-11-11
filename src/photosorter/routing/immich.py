import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import piexif

from photosorter.routing.dates import folder_for, resolve_date

EXIF_WRITABLE = {"jpg", "jpeg"}


@dataclass
class PlannedCopy:
    sha256: str
    source: Path
    target: Path
    date: datetime | None
    date_source: str
    write_date: bool
    reason: str


@dataclass
class Report:
    planned: list[PlannedCopy] = field(default_factory=list)
    skipped_existing: int = 0
    run_id: int | None = None

    def per_month(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.planned:
            key = folder_for(p.date)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def undated(self) -> int:
        return sum(1 for p in self.planned if p.date is None)

    def per_date_source(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.planned:
            counts[p.date_source] = counts.get(p.date_source, 0) + 1
        return counts


def _sql_in(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def _exported(conn) -> tuple[set[str], set[str]]:
    """Return (exported source paths, exported target paths) for live Immich runs.

    Only rows whose copy still exists count as exported, so a row left behind by a
    crash does not hide a photo that was never written.
    """
    rows = conn.execute(
        "SELECT m.target, m.source FROM manifest m JOIN runs r ON r.run_id = m.run_id "
        "WHERE r.target = 'immich' AND r.undone = 0 AND r.dry_run = 0"
    ).fetchall()
    rows = [r for r in rows if Path(r["target"]).exists()]
    return {r["source"] for r in rows}, {r["target"] for r in rows}


def _sidecar_path(target: Path) -> Path | None:
    """The sidecar `_write_date` would create for this target, if any."""
    if target.suffix.lower().lstrip(".") in EXIF_WRITABLE:
        return None
    return target.with_name(target.name + ".xmp")


class _Namer:
    """Picks target names that are free on disk and unique ignoring case."""

    def __init__(self, exported_targets: set[str]):
        self.taken = {t.casefold() for t in exported_targets}
        self._listings: dict[Path, set[str]] = {}

    def _on_disk(self, path: Path) -> bool:
        folder = path.parent
        if folder not in self._listings:
            try:
                self._listings[folder] = {p.name.casefold() for p in folder.iterdir()}
            except (FileNotFoundError, NotADirectoryError):
                self._listings[folder] = set()
        return path.name.casefold() in self._listings[folder] or path.is_symlink()

    def _free(self, path: Path) -> bool:
        names = [path]
        sidecar = _sidecar_path(path)
        if sidecar is not None:
            names.append(sidecar)
        return all(str(n).casefold() not in self.taken and not self._on_disk(n) for n in names)

    def claim(self, folder: Path, source: Path, sha256: str) -> Path:
        stem, suffix = source.stem, source.suffix
        candidates = [folder / source.name, folder / f"{stem}_{sha256[:8]}{suffix}", folder / f"{stem}_{sha256[:16]}{suffix}"]
        n = 2
        while True:
            for target in candidates:
                if self._free(target):
                    self.taken.add(str(target).casefold())
                    sidecar = _sidecar_path(target)
                    if sidecar is not None:
                        self.taken.add(str(sidecar).casefold())
                    return target
            candidates = [folder / f"{stem}_{sha256[:8]}_{n}{suffix}"]
            n += 1


def plan(conn, export_dir: Path, include_types: list[str], include_values: list[str]) -> Report:
    report = Report()
    rows = conn.execute(
        f"SELECT * FROM photos WHERE type IN ({_sql_in(include_types)}) "
        f"AND value IN ({_sql_in(include_values)}) ORDER BY path",
        [*include_types, *include_values],
    ).fetchall()
    exported_sources, exported_targets = _exported(conn)
    namer = _Namer(exported_targets)
    for row in rows:
        source = Path(row["path"])
        mtime = float(datetime.fromisoformat(row["mtime"]).replace(tzinfo=timezone.utc).timestamp()) if row["mtime"] else None
        dt, date_source = resolve_date(row["exif_date"], source.name, mtime)
        folder = export_dir / folder_for(dt)
        if str(source) in exported_sources:
            report.skipped_existing += 1
            continue
        target = namer.claim(folder, source, row["sha256"])
        report.planned.append(
            PlannedCopy(
                sha256=row["sha256"],
                source=source,
                target=target,
                date=dt,
                date_source=date_source,
                write_date=row["exif_date"] is None or date_source != "exif",
                reason=row["reason"] or "",
            )
        )
    return report


def _xmp(dt: datetime) -> str:
    stamp = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about="" xmlns:exif="http://ns.adobe.com/exif/1.0/"\n'
        f'   exif:DateTimeOriginal="{stamp}"/>\n'
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>\n'
    )


def _write_date(target: Path, dt: datetime) -> str | None:
    """Write the resolved date into the copy only. Returns the sidecar path if one was made."""
    suffix = target.suffix.lower().lstrip(".")
    if suffix in EXIF_WRITABLE:
        try:
            exif = piexif.load(str(target))
        except Exception:
            exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        stamp = dt.strftime("%Y:%m:%d %H:%M:%S").encode("ascii")
        exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = stamp
        exif["Exif"][piexif.ExifIFD.DateTimeDigitized] = stamp
        piexif.insert(piexif.dump(exif), str(target))
        return None
    sidecar = target.with_name(target.name + ".xmp")
    with open(sidecar, "x", encoding="utf-8") as f:  # never overwrite an existing file
        f.write(_xmp(dt))
    return str(sidecar)


def export(
    conn,
    export_dir: Path,
    include_types: tuple[str, ...] = ("people",),
    include_values: tuple[str, ...] = ("keep",),
    write_exif_for_undated: bool = True,
    dry_run: bool = True,
) -> Report:
    export_dir = Path(export_dir)
    report = plan(conn, export_dir, list(include_types), list(include_values))
    if dry_run:
        return report

    cur = conn.execute(
        "INSERT INTO runs (started_at, target, dry_run) VALUES (?, 'immich', 0)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    report.run_id = cur.lastrowid
    conn.commit()  # the run must exist on disk before any file is written
    for item in report.planned:
        _export_one(conn, report.run_id, item, write_exif_for_undated)
    return report


def _export_one(conn, run_id: int, item: PlannedCopy, write_exif_for_undated: bool) -> None:
    item.target.parent.mkdir(parents=True, exist_ok=True)
    will_write_date = item.date is not None and item.write_date and write_exif_for_undated
    sidecar = _sidecar_path(item.target) if will_write_date else None
    sidecar_existed = sidecar is not None and sidecar.exists()
    # Record the manifest row first and commit it, so any file that reaches the disk is covered.
    cur = conn.execute(
        "INSERT INTO manifest (run_id, source, target, sidecar, date_source, resolved, reason) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            run_id,
            str(item.source),
            str(item.target),
            str(sidecar) if sidecar is not None else None,
            item.date_source,
            item.date.isoformat() if item.date else None,
            item.reason,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    created = False
    try:
        # "xb" fails instead of overwriting; `created` stays False if the file was not ours.
        with open(item.source, "rb") as src, open(item.target, "xb") as dst:
            created = True
            shutil.copyfileobj(src, dst)
        shutil.copystat(item.source, item.target)  # keep file times, as copy2 does
        if will_write_date:
            _write_date(item.target, item.date)
    except BaseException:
        if created and item.target.exists():
            item.target.unlink()
        if sidecar is not None and not sidecar_existed and sidecar.exists():
            sidecar.unlink()
        conn.execute("DELETE FROM manifest WHERE id = ?", (row_id,))
        conn.commit()
        raise


def undo_last(conn, export_dir: Path) -> int:
    """Remove copies and sidecars from the last Immich run.

    Phase 1 checks every manifest row and raises ValueError before anything is deleted.
    Phase 2 deletes and prunes empty folders. The run is marked undone only after phase 2.
    """
    export_dir = Path(export_dir).resolve()
    run = conn.execute(
        "SELECT run_id FROM runs WHERE target = 'immich' AND dry_run = 0 AND undone = 0 "
        "ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return 0
    rows = conn.execute("SELECT target, sidecar FROM manifest WHERE run_id = ?", (run["run_id"],)).fetchall()

    originals = {
        r[0] for r in conn.execute("SELECT source FROM manifest UNION SELECT path FROM photos")
    }
    original_paths = {Path(o).resolve() for o in originals}

    to_delete: list[Path] = []
    for row in rows:
        for name in (row["target"], row["sidecar"]):
            if not name:
                continue
            raw = Path(name)
            path = raw.parent.resolve() / raw.name  # resolve the folder, not the file itself
            if export_dir not in path.parents:
                raise ValueError(f"refusing to delete outside export dir: {path}")
            if path.is_symlink():
                raise ValueError(f"refusing to delete a symlink: {path}")
            if path in original_paths:
                raise ValueError(f"refusing to delete an original photo: {path}")
            to_delete.append(path)

    removed = 0
    for path in to_delete:
        if path.exists():
            path.unlink()
            removed += 1
    for path in to_delete:
        parent = path.parent
        while parent != export_dir and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    conn.execute("UPDATE runs SET undone = 1 WHERE run_id = ?", (run["run_id"],))
    conn.commit()
    return removed
