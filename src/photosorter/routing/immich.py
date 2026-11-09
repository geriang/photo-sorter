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
    """Return (exported source paths, exported target paths) for live Immich runs."""
    rows = conn.execute(
        "SELECT m.target, m.source FROM manifest m JOIN runs r ON r.run_id = m.run_id "
        "WHERE r.target = 'immich' AND r.undone = 0 AND r.dry_run = 0"
    ).fetchall()
    return {r["source"] for r in rows}, {r["target"] for r in rows}


def plan(conn, export_dir: Path, include_types: list[str], include_values: list[str]) -> Report:
    report = Report()
    rows = conn.execute(
        f"SELECT * FROM photos WHERE type IN ({_sql_in(include_types)}) "
        f"AND value IN ({_sql_in(include_values)}) ORDER BY path",
        [*include_types, *include_values],
    ).fetchall()
    exported_sources, exported_targets = _exported(conn)
    claimed: set[str] = set()
    for row in rows:
        source = Path(row["path"])
        mtime = float(datetime.fromisoformat(row["mtime"]).replace(tzinfo=timezone.utc).timestamp()) if row["mtime"] else None
        dt, date_source = resolve_date(row["exif_date"], source.name, mtime)
        folder = export_dir / folder_for(dt)
        target = folder / source.name
        if str(source) in exported_sources:
            report.skipped_existing += 1
            continue
        if target.exists() or str(target) in claimed or str(target) in exported_targets:
            target = folder / f"{source.stem}_{row['sha256'][:8]}{source.suffix}"
        claimed.add(str(target))
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
    sidecar.write_text(_xmp(dt), encoding="utf-8")
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
    for item in report.planned:
        item.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.source, item.target)
        sidecar = None
        if item.date is not None and item.write_date and write_exif_for_undated:
            sidecar = _write_date(item.target, item.date)
        conn.execute(
            "INSERT INTO manifest (run_id, source, target, sidecar, date_source, resolved, reason) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                report.run_id,
                str(item.source),
                str(item.target),
                sidecar,
                item.date_source,
                item.date.isoformat() if item.date else None,
                item.reason,
            ),
        )
    conn.commit()
    return report


def undo_last(conn, export_dir: Path) -> int:
    """Remove copies and sidecars from the last Immich run. Never touches paths outside export_dir."""
    export_dir = Path(export_dir).resolve()
    run = conn.execute(
        "SELECT run_id FROM runs WHERE target = 'immich' AND dry_run = 0 AND undone = 0 "
        "ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return 0
    removed = 0
    rows = conn.execute("SELECT target, sidecar FROM manifest WHERE run_id = ?", (run["run_id"],)).fetchall()
    for row in rows:
        for name in (row["target"], row["sidecar"]):
            if not name:
                continue
            path = Path(name).resolve()
            if export_dir not in path.parents:
                raise ValueError(f"refusing to delete outside export dir: {path}")
            if path.exists():
                path.unlink()
                removed += 1
            parent = path.parent
            while parent != export_dir and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
    conn.execute("UPDATE runs SET undone = 1 WHERE run_id = ?", (run["run_id"],))
    conn.commit()
    return removed
