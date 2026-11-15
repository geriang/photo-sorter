import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_lockdown", ROOT / "scripts/immich/check_lockdown.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_shipped_override_passes_static_checks():
    text = (ROOT / "scripts/immich/docker-compose.override.yml").read_text()
    results = check.check_override(text)
    assert all(ok for ok, _ in results), results


def test_override_missing_telemetry_flag_fails():
    text = (ROOT / "scripts/immich/docker-compose.override.yml").read_text().replace("ORT_DISABLE_TELEMETRY", "X")
    assert not all(ok for ok, _ in check.check_override(text))


def test_version_checks():
    assert check.check_env("IMMICH_VERSION=v3.3.6\n")[0][0]
    assert check.check_env("IMMICH_VERSION=v3.4.0\n")[0][0]
    assert not check.check_env("IMMICH_VERSION=v3.3.5\n")[0][0]
    assert not check.check_env("IMMICH_VERSION=release\n")[0][0]
    assert not check.check_env("")[0][0]
