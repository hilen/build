#!/usr/bin/env -S uv run -q --no-dev
# Puts a Mac bundle of a built binary into /Applications on this machine, for a
# look at what only a bundle has, like the icon in Finder and Open With. It is
# signed for this machine only, a release goes through mac.py. Run it from the
# app folder after the binary is in target/release, like after `far get`. It
# reads hilen.toml and not cargo, a machine that only runs apps has no cargo.

import shutil
import subprocess
from pathlib import Path
from typing import Final

import msgspec
from mac import bundle
from shared.release import Release
from shared.util import bail, run_main

from shared import bluetooth, camera, links, open_files, speech, toml

_LSREGISTER: Final = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)


class _App(msgspec.Struct, frozen=True):
    project_name: str
    bundle_id: str
    version: str


def _read(text: str) -> Release:
    app = toml.decode(text, _App, "hilen.toml")
    return Release(
        name=app.project_name,
        bin=app.project_name,
        version=app.version,
        bundle_id=app.bundle_id,
        download_url="",
        host_deployment="",
        target_subdir="",
        mac_targets=(),
        self_update=False,
        daemons=(),
        link_scheme=links.scheme_of(text),
        camera_usage=camera.usage_of(text),
        bluetooth_usage=bluetooth.usage_of(text),
        speech_usage=speech.usage_of(text),
        open_file_types=open_files.types_of(text),
    )


def main() -> int:
    r = _read(Path("hilen.toml").read_text(encoding="utf-8"))
    binary = Path("target/release") / r.name
    if not binary.is_file():
        bail(f"{binary} is not built")
    app = bundle(r, str(binary))
    subprocess.run(["codesign", "--force", "--sign", "-", app], check=True)
    target = Path("/Applications") / f"{r.name}.app"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(app, target, symlinks=True)
    # The system also registers the bundle in target, and Open With then lists
    # the app twice.
    # A bundle the system did not register answers -10814, not found, and
    # then there is nothing to take back.
    unregistered = subprocess.run([_LSREGISTER, "-u", app], check=False)
    if unregistered.returncode != 0:
        print(f"lsregister had no {app} to take back, code {unregistered.returncode}")
    shutil.rmtree(app)
    subprocess.run([_LSREGISTER, "-f", str(target)], check=True)
    print(f"installed {target}")
    return 0


if __name__ == "__main__":
    run_main(main)
