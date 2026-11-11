#!/usr/bin/env python3
"""Check the Immich lockdown settings. Exit code 1 if any check fails.

Static checks read the override file and the Immich .env. If Docker is available,
runtime checks inspect the running containers. Nothing here changes any setting.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

MIN_VERSION = (3, 3, 6)


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", text.strip())
    return tuple(int(g) for g in m.groups()) if m else None


def check_env(env_text: str) -> list[tuple[bool, str]]:
    results = []
    m = re.search(r"^IMMICH_VERSION=(.*)$", env_text, re.M)
    if not m:
        results.append((False, "IMMICH_VERSION is not set; pin it to 3.3.6 or later (not 'release')"))
        return results
    value = m.group(1).strip().strip("'\"")
    version = parse_version(value)
    if version is None:
        results.append((False, f"IMMICH_VERSION={value!r} is not an exact version; pin e.g. v3.3.6"))
    elif version < MIN_VERSION:
        results.append((False, f"IMMICH_VERSION={value} is older than 3.3.6 (telemetry fix)"))
    else:
        results.append((True, f"IMMICH_VERSION={value} includes the telemetry fix"))
    return results


def check_override(text: str) -> list[tuple[bool, str]]:
    return [
        (bool(re.search(r'ORT_DISABLE_TELEMETRY:\s*"?1"?', text)), "ML sets ORT_DISABLE_TELEMETRY=1"),
        (bool(re.search(r"ml_internal:\s*\n\s*internal:\s*true", text)), "ml_internal network is internal: true"),
        (bool(re.search(r'profiles:\s*\[\s*"ml-hardened"\s*\]', text)), "ML only starts with --profile ml-hardened"),
        (bool(re.search(r"/external/people:ro", text)), "export folder is mounted read-only"),
    ]


def check_runtime() -> list[tuple[bool, str]]:
    if not shutil.which("docker"):
        return [(True, "docker not found: runtime checks skipped")]
    results = []
    out = subprocess.run(
        ["docker", "inspect", "immich_machine_learning"], capture_output=True, text=True
    )
    if out.returncode != 0:
        return [(True, "ML container is not running (ML off): nothing to check at runtime")]
    info = json.loads(out.stdout)[0]
    env = info["Config"].get("Env", [])
    results.append(("ORT_DISABLE_TELEMETRY=1" in env, "running ML container has ORT_DISABLE_TELEMETRY=1"))
    for net in info["NetworkSettings"]["Networks"]:
        inspect = subprocess.run(["docker", "network", "inspect", net], capture_output=True, text=True)
        internal = inspect.returncode == 0 and json.loads(inspect.stdout)[0].get("Internal", False)
        results.append((internal, f"ML network {net!r} is internal"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--override", default=str(Path(__file__).with_name("docker-compose.override.yml")))
    parser.add_argument("--env", default=".env", help="Immich .env file")
    args = parser.parse_args()

    results = check_override(Path(args.override).read_text())
    env_path = Path(args.env)
    if env_path.exists():
        results += check_env(env_path.read_text())
    else:
        results.append((False, f"{env_path} not found; cannot check IMMICH_VERSION"))
    results += check_runtime()

    for ok, message in results:
        print(f"[{'ok' if ok else 'FAIL'}] {message}")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
