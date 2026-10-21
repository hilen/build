#!/usr/bin/env -S uv run -q --no-dev

# Tags and pushes a release, CI builds from the tag. `patch` or `minor` bumps the
# newest `v*` tag, writes the version into Cargo.toml and Cargo.lock, commits,
# tags and pushes.

import re
import sys
from pathlib import Path
from typing import Final

from shared.run import capture, has, probe, run
from shared.util import bail, run_main

_TAG: Final = re.compile(r"^v(\d+)\.(\d+)\.(\d+)")
_VERSION_LINE: Final = re.compile(r'(?m)^(version\s*=\s*)"[^"]+"')


def latest_tag(described: str) -> tuple[int, int, int]:
    found = _TAG.match(described.strip())
    if found is None:
        return 0, 0, 0
    return int(found[1]), int(found[2]), int(found[3])


def bump(cargo: str, version: str) -> str:
    if _VERSION_LINE.search(cargo) is None:
        bail("no version line in Cargo.toml")
    return _VERSION_LINE.sub(lambda m: f'{m[1]}"{version}"', cargo, count=1)


def _write_version(version: str):
    path = Path("Cargo.toml")
    path.write_text(bump(path.read_text(encoding="utf-8"), version), encoding="utf-8")
    # Cargo.lock carries the version of every workspace package, cargo rewrites
    # only those. A stale one fails the --locked release build, and the next cargo
    # run would leave the tree dirty after a release. A machine with no Rust
    # toolchain has no cargo, far runs it on a build machine and brings the lock
    # file back.
    run("cargo update --workspace" if has("cargo") else "far cargo update --workspace")


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    if kind not in {"patch", "minor"}:
        bail("usage: tag.py patch|minor")
    # A version bump commit must not sweep up unrelated changes.
    if capture("git status --porcelain").strip():
        bail("working tree has uncommitted changes, commit or stash first")
    major, minor, patch = latest_tag(probe("git describe --tags --abbrev=0 --match=v*"))
    version = f"{major}.{minor}.{patch + 1}" if kind == "patch" else f"{major}.{minor + 1}.0"
    _write_version(version)
    tag = f"v{version}"
    run("git add Cargo.toml Cargo.lock")
    # A first release can find the version already written, then the commit it
    # would make is empty and git refuses it.
    if not capture("git diff --cached --name-only"):
        print(f"Cargo.toml already says {version}, tagging HEAD")
    else:
        run(f'git commit -m "release {tag}"')
    run(f"git tag {tag}")
    run(f"git push origin HEAD {tag}")
    print(f"released {tag}")
    return 0


if __name__ == "__main__":
    run_main(main)
