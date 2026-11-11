"""Regression tests for reviewer findings 1-5 and the undo safety condition."""
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from photosorter import cli
from photosorter.cli import main
from photosorter.db.schema import connect
from photosorter.faces.detector import detect_people
from photosorter.ingest.scan import scan
from photosorter.routing import immich
from photosorter.scoring.default import apply_default_scoring
from tests.conftest import StubDetector, make_jpeg


def prepare(conn, library):
    scan(conn, library)
    detect_people(conn, StubDetector())
    apply_default_scoring(conn)


def write_config(tmp_path, src, out):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[paths]\nsource = "{src}"\n[immich]\nexport_dir = "{out}"\n')
    return ["--config", str(cfg), "--db", str(tmp_path / "db.sqlite")]


# Finding 1: documented workflow must work without editing the database by hand
def test_cli_workflow_exports_people_without_manual_db_edits(tmp_path, monkeypatch):
    src = tmp_path / "photos"
    make_jpeg(src / "person_20240101_120000.jpg")
    make_jpeg(src / "landscape_20240102_120000.jpg")
    out = tmp_path / "Immich"
    base = write_config(tmp_path, src, out)
    monkeypatch.setattr(cli, "load_detector", lambda: StubDetector(), raising=False)

    assert main(base + ["scan"]) == 0
    assert main(base + ["faces"]) == 0
    assert main(base + ["score"]) == 0
    assert main(base + ["apply", "--target", "immich", "--yes"]) == 0
    assert [p.name for p in out.rglob("*.jpg")] == ["person_20240101_120000.jpg"]


def test_score_refuses_when_faces_have_not_been_detected(tmp_path, capsys):
    src = tmp_path / "photos"
    make_jpeg(src / "person_20240101_120000.jpg")
    base = write_config(tmp_path, src, tmp_path / "Immich")
    main(base + ["scan"])
    assert main(base + ["score"]) == 1
    assert "faces" in capsys.readouterr().err


# Finding 2: an export that fails partway must still be undoable
def test_failed_export_can_be_undone_from_a_fresh_connection(library, tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    conn = connect(db)
    prepare(conn, library)
    out = tmp_path / "Immich"

    real = immich._write_date
    calls = {"n": 0}

    def flaky(target, dt):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return real(target, dt)

    monkeypatch.setattr(immich, "_write_date", flaky)
    with pytest.raises(RuntimeError):
        immich.export(conn, out, dry_run=False)
    conn.close()  # a crashed process loses anything uncommitted

    conn2 = connect(db)
    immich.undo_last(conn2, out)
    assert [p for p in out.rglob("*") if p.is_file()] == []


def test_failed_export_does_not_leave_the_failed_item_marked_as_exported(library, tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    conn = connect(db)
    prepare(conn, library)
    out = tmp_path / "Immich"
    monkeypatch.setattr(immich, "_write_date", lambda t, d: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        immich.export(conn, out, dry_run=False)
    monkeypatch.undo()
    report = immich.export(conn, out, dry_run=False)
    assert report.skipped_existing == 0 or all(p.target.exists() for p in report.planned)
    names = [p.name for p in out.rglob("*.jpg")]
    assert len(names) == len(set(names)) == 5


# Finding 3: never overwrite, even on a case-insensitive filesystem (macOS)
def test_foreign_files_at_candidate_names_are_never_overwritten(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    folder = out / "2024" / "06"
    folder.mkdir(parents=True)
    foreign = {}
    foreign[folder / "person_dup.jpg"] = b"foreign-1"
    for row in conn.execute("SELECT sha256, path FROM photos WHERE path LIKE '%person_dup.jpg'"):
        foreign[folder / f"person_dup_{row['sha256'][:8]}.jpg"] = b"foreign-" + row["sha256"][:4].encode()
    for path, data in foreign.items():
        path.write_bytes(data)

    immich.export(conn, out, dry_run=False)

    for path, data in foreign.items():
        assert path.read_bytes() == data
    exported_dups = [p for p in folder.glob("person_dup*") if p not in foreign]
    assert len(exported_dups) == 2


def test_names_differing_only_by_case_do_not_collide(conn, tmp_path):
    root = tmp_path / "photos"
    make_jpeg(root / "x" / "person_A.jpg", (1, 2, 3), exif_date="2024:05:01 10:00:00")
    make_jpeg(root / "y" / "PERSON_a.JPG", (4, 5, 6), exif_date="2024:05:02 10:00:00")
    prepare(conn, root)
    report = immich.plan(conn, tmp_path / "Immich", ["people"], ["keep"])
    keys = [str(p.target).casefold() for p in report.planned]
    assert len(keys) == len(set(keys)) == 2


# Finding 4: re-scan must keep detection and scoring results
def test_rescan_keeps_detection_and_scoring(conn, library):
    prepare(conn, library)
    before = [tuple(r) for r in conn.execute(
        "SELECT sha256, has_people, group_size, type, value, score, reason FROM photos ORDER BY sha256")]
    scan(conn, library)
    after = [tuple(r) for r in conn.execute(
        "SELECT sha256, has_people, group_size, type, value, score, reason FROM photos ORDER BY sha256")]
    assert before == after
    assert any(r[1] == 1 for r in after)


# Finding 5: a refused path must not leave a half-undone run
def test_undo_with_a_bad_row_deletes_nothing_and_keeps_run_open(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    victim = tmp_path / "keep_me.txt"
    victim.write_text("x")
    last = conn.execute("SELECT id FROM manifest ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE manifest SET target = ? WHERE id = ?", (str(victim), last))
    before = sorted(p for p in out.rglob("*") if p.is_file())
    with pytest.raises(ValueError):
        immich.undo_last(conn, out)
    assert sorted(p for p in out.rglob("*") if p.is_file()) == before
    assert victim.exists()
    assert conn.execute("SELECT undone FROM runs").fetchone()["undone"] == 0


# Condition (d): undo only deletes manifest-listed files inside the output folder, never originals
def test_undo_never_deletes_an_original_even_inside_the_export_dir(conn, tmp_path):
    out = tmp_path / "Immich"
    original = make_jpeg(out / "2024" / "06" / "person_orig.jpg", exif_date="2024:06:01 10:00:00")
    scan(conn, out)
    detect_people(conn, StubDetector())
    apply_default_scoring(conn)
    conn.execute("INSERT INTO runs (started_at, target, dry_run) VALUES ('now', 'immich', 0)")
    conn.execute(
        "INSERT INTO manifest (run_id, source, target, date_source) VALUES (1, ?, ?, 'exif')",
        (str(original), str(original)),
    )
    with pytest.raises(ValueError):
        immich.undo_last(conn, out)
    assert original.exists()


def test_undo_never_follows_a_symlink_to_an_original(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    original = library / "a" / "person_dated.jpg"
    link = out / "2024" / "06" / "link.jpg"
    link.parent.mkdir(parents=True)
    link.symlink_to(original)
    conn.execute("INSERT INTO runs (started_at, target, dry_run) VALUES ('now', 'immich', 0)")
    conn.execute(
        "INSERT INTO manifest (run_id, source, target, date_source) VALUES (1, ?, ?, 'exif')",
        (str(original), str(link)),
    )
    with pytest.raises(ValueError):
        immich.undo_last(conn, out)
    assert original.exists()


def test_undo_leaves_unrecorded_files_in_the_export_dir_alone(conn, library, tmp_path):
    prepare(conn, library)
    out = tmp_path / "Immich"
    immich.export(conn, out, dry_run=False)
    stray = out / "2024" / "06" / "my_own_file.txt"
    stray.write_text("mine")
    immich.undo_last(conn, out)
    assert stray.read_text() == "mine"
