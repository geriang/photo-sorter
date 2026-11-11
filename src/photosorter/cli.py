import argparse
import sys
import tomllib
from pathlib import Path

from photosorter.db.schema import connect
from photosorter.faces.detector import detect_people
from photosorter.ingest.scan import scan
from photosorter.routing import immich
from photosorter.scoring.default import apply_default_scoring

DEFAULT_DB = "data/db/photosorter.sqlite"


def _load_config(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_detector():
    """Build the face detector. Imported lazily so InsightFace is only needed for `faces`."""
    from photosorter.faces.detector import InsightFaceDetector

    return InsightFaceDetector()


def _print_report(report: immich.Report, dry_run: bool) -> None:
    mode = "DRY RUN (nothing written)" if dry_run else "APPLIED"
    print(f"Immich export: {mode}")
    print(f"  photos to copy:   {len(report.planned)}")
    print(f"  already exported: {report.skipped_existing}")
    print(f"  undated:          {report.undated()}")
    print(f"  date sources:     {report.per_date_source()}")
    for month, count in report.per_month().items():
        print(f"  {month:<10} {count}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="photosorter")
    parser.add_argument("--config", default="config/config.toml")
    parser.add_argument("--db", default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="hash and record every image under paths.source")
    sub.add_parser("faces", help="detect people in scanned photos (needs the `faces` extra)")
    sub.add_parser("score", help="apply default scoring (placeholder until Milestone 4)")

    apply_p = sub.add_parser("apply", help="copy photos to an output target")
    apply_p.add_argument("--target", choices=["immich"], required=True)
    apply_p.add_argument("--yes", action="store_true", help="really copy files (default is dry run)")

    undo_p = sub.add_parser("undo", help="remove copies made by the last run")
    undo_p.add_argument("--last-run", action="store_true", required=True)

    args = parser.parse_args(argv)
    config = _load_config(args.config)
    conn = connect(args.db)
    immich_cfg = config.get("immich", {})
    export_dir = Path(immich_cfg.get("export_dir", "./output/Sorted/Immich"))

    if args.command == "scan":
        paths = config["paths"]
        print(f"scanned {scan(conn, Path(paths['source']), paths.get('skip_dirs', []))} images")
    elif args.command == "faces":
        try:
            detector = load_detector()
        except ImportError:
            print("error: InsightFace is not installed. Run `pip install .[faces]` first.", file=sys.stderr)
            return 1
        print(f"checked {detect_people(conn, detector)} photos for people")
    elif args.command == "score":
        pending = conn.execute("SELECT COUNT(*) FROM photos WHERE has_people IS NULL").fetchone()[0]
        if pending:
            print(
                f"error: {pending} photos have no face detection yet. Run `photosorter faces` before `score`.",
                file=sys.stderr,
            )
            return 1
        scoring = config.get("scoring", {})
        n = apply_default_scoring(conn, scoring.get("keep_above", 0.7), scoring.get("toss_below", 0.3))
        print(f"scored {n} photos")
    elif args.command == "apply":
        dry_run = not args.yes
        report = immich.export(
            conn,
            export_dir,
            tuple(immich_cfg.get("include_types", ["people"])),
            tuple(immich_cfg.get("include_values", ["keep"])),
            immich_cfg.get("write_exif_for_undated", True),
            dry_run=dry_run,
        )
        _print_report(report, dry_run)
    elif args.command == "undo":
        print(f"removed {immich.undo_last(conn, export_dir)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
