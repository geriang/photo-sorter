import hashlib
from pathlib import Path

import piexif
import pytest
from PIL import Image

from photosorter.faces.detector import detect_people
from photosorter.ingest.scan import scan
from photosorter.routing import immich
from photosorter.scoring.default import apply_default_scoring
from tests.conftest import StubDetector, make_jpeg


def prepare(conn, library):
    scan(conn, library)
    detect_people(conn, StubDetector())
    apply_default_scoring(conn)


def tree_hashes(root: Path) -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def test_dry_run_writes_nothing(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    report = immich.export(conn, out, dry_run=True)
    assert len(report.planned) == 5
    assert not out.exists()
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_only_people_and_keep_are_exported(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    names = {p.name for p in out.rglob("*.jpg")}
    assert "landscape.jpg" not in names
    assert len(names) == 5


def test_year_month_layout_and_date_sources(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    report = immich.export(conn, out, dry_run=False)
    rel = {str(p.relative_to(out)) for p in out.rglob("*.jpg")}
    assert "2024/06/person_dated.jpg" in rel
    assert "2023/07/person_20230704_101500.jpg" in rel
    assert "2021/03/person_mtime.jpg" in rel
    assert report.per_date_source() == {"exif": 3, "filename": 1, "mtime": 1}
    assert report.undated() == 0


def test_filename_collision_gets_hash_suffix(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    dups = sorted(p.name for p in (out / "2024" / "06").glob("person_dup*"))
    assert len(dups) == 2
    assert "person_dup.jpg" in dups
    assert any(n.startswith("person_dup_") for n in dups)


def test_undated_copy_gets_exif_date_but_original_untouched(conn, library, tmp_path):
    prepare(conn, library)
    before = tree_hashes(library)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    assert tree_hashes(library) == before
    copy = out / "2023" / "07" / "person_20230704_101500.jpg"
    exif = piexif.load(str(copy))
    assert exif["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2023:07:04 10:15:00"
    original = library / "b" / "person_20230704_101500.jpg"
    assert piexif.ExifIFD.DateTimeOriginal not in piexif.load(str(original))["Exif"]


def test_exif_dated_copy_is_not_rewritten(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    src = library / "a" / "person_dated.jpg"
    copy = out / "2024" / "06" / "person_dated.jpg"
    assert copy.read_bytes() == src.read_bytes()


def test_png_gets_xmp_sidecar(conn, tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    Image.new("RGB", (16, 16)).save(root / "person_20220101_000000.png")
    prepare(conn, root)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    sidecar = out / "2022" / "01" / "person_20220101_000000.png.xmp"
    assert sidecar.exists()
    assert 'exif:DateTimeOriginal="2022-01-01T00:00:00"' in sidecar.read_text()


def test_undated_goes_to_undated_folder(conn, tmp_path):
    root = tmp_path / "photos"
    p = make_jpeg(root / "person_x.jpg")
    prepare(conn, root)
    conn.execute("UPDATE photos SET mtime = NULL")
    out = tmp_path / "Immich"
    report = immich.export(conn, out, dry_run=False)
    assert (out / "Undated" / "person_x.jpg").exists()
    assert report.undated() == 1
    assert p.exists()


def test_rerun_skips_already_exported(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    again = immich.export(conn, out, dry_run=False)
    assert again.planned == []
    assert again.skipped_existing == 5


def test_undo_removes_copies_sidecars_and_empty_dirs(conn, library, tmp_path):
    root = library
    Image.new("RGB", (16, 16)).save(root / "person_20220101_000000.png")
    prepare(conn, root)
    before = tree_hashes(root)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    removed = immich.undo_last(conn, out)
    assert removed == 7
    assert not any(out.rglob("*.*"))
    assert [p for p in out.rglob("*") if p.is_dir()] == []
    assert tree_hashes(root) == before
    assert immich.undo_last(conn, out) == 0


def test_undo_refuses_paths_outside_export_dir(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    victim = tmp_path / "keep_me.txt"
    victim.write_text("x")
    conn.execute("UPDATE manifest SET target = ?", (str(victim),))
    with pytest.raises(ValueError):
        immich.undo_last(conn, out)
    assert victim.exists()
