#!/usr/bin/env -S uv run -q --no-dev

# Writes dist/manifest.json for the website and dist/updater.json for the engine
# updater, plus dist/<daemon>-updater.json for each daemon of the `daemons` list.
# Which files are there comes from dist/ by default, or from a file listing the
# names on the download host with `--present <file>`, the CI case where only the
# .meta.json sidecars were pulled back to the runner.

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from shared.util import bail, eprint, run_main

from shared import manifest, release

if TYPE_CHECKING:
    from shared.release import Release


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def _present(args: Sequence[str]) -> set[str]:
    if "--present" not in args:
        return {p.name for p in Path("dist").iterdir()}
    at = args.index("--present") + 1
    if at >= len(args):
        bail("--present needs a file")
    text = Path(args[at]).read_text(encoding="utf-8")
    return {line.strip() for line in text.splitlines() if line.strip()}


def _has(present: set[str], artifact: Callable[[str], str]) -> manifest.Has:
    def has(suffix: str) -> str | None:
        name = artifact(suffix)
        return name if name in present else None

    return has


def _write_updater(
    file: str, r: Release, version: str, entries: Sequence[tuple[str, str]], has: manifest.Has
):
    text = manifest.updater(r, version, entries, has, _read)
    if text is None:
        eprint(f"warn: no signed update artifacts, skipping {file}")
        return
    Path(f"dist/{file}").write_text(f"{text}\n", encoding="utf-8")
    print(text)


def main() -> int:
    r = release.read()
    present = _present(sys.argv[1:])
    has = _has(present, r.artifact)
    text = manifest.site(r, has)
    Path("dist/manifest.json").write_text(f"{text}\n", encoding="utf-8")
    print(text)

    _write_updater(
        "updater.json", r, r.version, [*manifest.bare_entries(r), *manifest.APPIMAGES], has
    )
    # A daemon is a bare binary on every platform, no AppImage.
    for daemon in r.daemons:
        daemon_has = _has(present, daemon.artifact)
        _write_updater(daemon.manifest(), r, daemon.version, manifest.bare_entries(r), daemon_has)
    return 0


if __name__ == "__main__":
    run_main(main)
