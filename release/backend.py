#!/usr/bin/env -S uv run -q --no-dev

# Publishes a release to a Gebling backend, the server of polyraiders.com. It
# takes files at /artifacts/<product>/<version>/<file> and puts a version live on
# /finalize once all 4 are there: the Windows installer, the Mac dmg, the Linux
# zip and a server zip. The product is the package name.
#
#   backend.py windows|mac|linux   uploads what the script of that platform built
#   backend.py finalize            uploads the server zip, then finalizes
#
# A game without a server of its own ships the server zip of the release that is
# live now, so the session manager keeps running the old one. BACKEND_URL and
# RELEASE_UPLOAD_TOKEN come from the env.

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import msgspec
from shared.run import capture, run
from shared.util import bail, run_main

from shared import release

if TYPE_CHECKING:
    from shared.release import Release

# The token stays a shell variable in the string, so no log shows its value.
_CURL: Final = (
    "curl --fail --show-error --silent --retry 3 --retry-all-errors "
    '-H "Authorization: Bearer $RELEASE_UPLOAD_TOKEN"'
)


class _Latest(msgspec.Struct, frozen=True):
    server_url: str


# A file of dist/ that the platform script built, by its suffix.
def _dist(r: Release, suffix: str) -> str:
    path = f"dist/{r.artifact(suffix)}"
    if not Path(path).is_file():
        bail(f"{path} is missing, run the release script of that platform first")
    return path


# The x64 binary alone in a zip, named like the app.
def _linux_zip(r: Release, version: str) -> str:
    bare = _dist(r, "linux-x86_64")
    stage = Path("target/backend-stage")
    stage.mkdir(parents=True, exist_ok=True)
    binary = stage / r.name
    shutil.copyfile(bare, binary)
    run(f"chmod +x {binary}")
    zip_path = Path(f"dist/{r.name}-linux-{version}.zip")
    zip_path.unlink(missing_ok=True)
    run(f"zip -j {zip_path} {binary}")
    return str(zip_path)


# Downloads the server zip of the live release into dist/.
def _server_zip(backend: str, product: str, version: str) -> str:
    text = capture(f"curl --fail --show-error --silent {backend}/releases/{product}/latest")
    try:
        latest = msgspec.json.decode(text, type=_Latest)
    except msgspec.MsgspecError as err:
        bail(f"the live release, a first release has no server zip to carry over: {err}")
    Path("dist").mkdir(exist_ok=True)
    path = f"dist/{product}-server-{version}.zip"
    run(f"curl --fail --show-error --silent --retry 3 -o {path} {backend}{latest.server_url}")
    print(f"carried over {latest.server_url} as {path}")
    return path


# `kind` picks the name the backend expects for the file.
def _upload(backend: str, product: str, version: str, file: str, kind: str):
    match kind:
        case "windows":
            name = f"{product}-windows-{version}-installer.exe"
        case "mac":
            name = f"{product}-mac-{version}.dmg"
        case "linux":
            name = f"{product}-linux-{version}.zip"
        case "server":
            name = f"{product}-server-{version}.zip"
        case other:
            bail(f"no backend name for '{other}'")
    run(f"{_CURL} --upload-file {file} {backend}/artifacts/{product}/{version}/{name}")
    print(f"uploaded {file} as {name}")


def main() -> int:
    r = release.read()
    backend = os.environ.get("BACKEND_URL")
    if backend is None:
        bail("BACKEND_URL is not set")
    backend = backend.rstrip("/")
    if "RELEASE_UPLOAD_TOKEN" not in os.environ:
        bail("RELEASE_UPLOAD_TOKEN is not set")
    version = f"v{r.version}"
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    match step:
        case "windows":
            file = _dist(r, "windows-x64-setup.exe")
        case "mac":
            file = _dist(r, "mac-universal.dmg")
        case "linux":
            file = _linux_zip(r, version)
        case "finalize":
            _upload(backend, r.name, version, _server_zip(backend, r.name, version), "server")
            run(f"{_CURL} -X POST {backend}/artifacts/{r.name}/{version}/finalize")
            print(f"{r.name} {version} is live")
            return 0
        case other:
            bail(f"unknown step '{other}', use windows, mac, linux or finalize")
    _upload(backend, r.name, version, file, step)
    return 0


if __name__ == "__main__":
    run_main(main)
