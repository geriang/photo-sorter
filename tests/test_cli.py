from photosorter.cli import main
from tests.conftest import make_jpeg


def test_cli_end_to_end_dry_run_then_apply_then_undo(tmp_path, capsys):
    src = tmp_path / "photos"
    make_jpeg(src / "person_20240101_120000.jpg")
    out = tmp_path / "Immich"
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[paths]\nsource = "{src}"\nskip_dirs = []\n'
        f'[immich]\nexport_dir = "{out}"\n[safety]\ndry_run = true\n'
    )
    db = str(tmp_path / "db.sqlite")
    base = ["--config", str(cfg), "--db", db]

    assert main(base + ["scan"]) == 0
    from photosorter.db.schema import connect
    conn = connect(db)
    conn.execute("UPDATE photos SET has_people = 1, group_size = 1")
    conn.commit()
    conn.close()
    assert main(base + ["score"]) == 0

    main(base + ["apply", "--target", "immich"])
    assert "DRY RUN" in capsys.readouterr().out
    assert not out.exists()

    main(base + ["apply", "--target", "immich", "--yes"])
    assert (out / "2024" / "01" / "person_20240101_120000.jpg").exists()

    main(base + ["undo", "--last-run"])
    assert not list(out.rglob("*.jpg"))


def test_apply_without_yes_never_writes_even_if_config_disables_dry_run(tmp_path):
    src = tmp_path / "photos"
    make_jpeg(src / "person_20240101_120000.jpg")
    out = tmp_path / "Immich"
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[paths]\nsource = "{src}"\n[immich]\nexport_dir = "{out}"\n[safety]\ndry_run = false\n'
    )
    db = str(tmp_path / "db.sqlite")
    base = ["--config", str(cfg), "--db", db]
    main(base + ["scan"])
    from photosorter.db.schema import connect
    conn = connect(db)
    conn.execute("UPDATE photos SET has_people = 1, group_size = 1")
    conn.commit()
    conn.close()
    main(base + ["score"])
    main(base + ["apply", "--target", "immich"])
    assert not out.exists()
