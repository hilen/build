#!/usr/bin/env -S uv run -q --no-dev

# The Windows release, cross built in docker with cargo-xwin and packed by NSIS.
# `--arch=x64|arm64`, both by default. Outputs in dist/:
#   <name>-<v>-windows-<arch>-setup.exe   first install
#   <name>-<v>-windows-<arch>.exe         the bare exe the updater swaps in
#   <daemon>-<v>-windows-<arch>.exe       each daemon of `daemons`, bare and signed

import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from shared.util import bail, run_main

from shared import docker, inspect, release

if TYPE_CHECKING:
    from shared.release import Release

_TARGETS: Final = (("x64", "x86_64-pc-windows-msvc"), ("arm64", "aarch64-pc-windows-msvc"))
# target/release-win is a docker volume, so everything the host reads back is
# staged into a sibling folder like the linux lane does.
_STAGE: Final = "target/win-stage/out"
_PLATFORM: Final = "linux/amd64"
_RELEASE: Final = "/work/apps/app/target/release-win"
_OUT: Final = f"/work/apps/app/{_STAGE}"


def _script(r: Release, targets: Sequence[tuple[str, str]]) -> str:
    lines = ["set -euo pipefail", "rustup component add rust-src"]
    # The installer registers the url scheme of the app when it has one.
    scheme = "" if r.link_scheme is None else f"-DSCHEME={r.link_scheme} "
    for arch, triple in targets:
        lines += [
            f"rustup target add {triple}",
            f"cargo xwin build --locked --release -p {r.name} --bin {r.bin} --target {triple}",
            (
                f"makensis {scheme}-DNAME={r.name} -DVERSION={r.version} "
                f"-DEXE={_RELEASE}/{triple}/release/{r.bin}.exe "
                "-DICON=/work/apps/app/assets/icon.ico "
                f"-DOUTPUT={_OUT}/{r.name}-{arch}-setup.exe build/release/installer.nsi"
            ),
            f"cp {_RELEASE}/{triple}/release/{r.bin}.exe {_OUT}/{r.name}-{arch}.exe",
        ]
        # A daemon is only its bare exe, no installer.
        for daemon in r.daemons:
            lines += [
                (
                    f"cargo xwin build --locked --release -p {daemon.name} --bin {daemon.bin} "
                    f"--target {triple}"
                ),
                f"cp {_RELEASE}/{triple}/release/{daemon.bin}.exe {_OUT}/{daemon.name}-{arch}.exe",
            ]
    return "\n".join(lines) + "\n"


def main() -> int:
    inspect.mark_release()
    r = release.read()
    only = next((a.removeprefix("--arch=") for a in sys.argv[1:] if a.startswith("--arch=")), None)
    targets = [(arch, triple) for arch, triple in _TARGETS if only is None or only == arch]
    if not targets:
        bail("unknown arch, use x64 or arm64")
    Path("dist").mkdir(exist_ok=True)
    Path(_STAGE).mkdir(parents=True, exist_ok=True)

    image = f"{r.name}-win-builder"
    docker.build_image(image, "Dockerfile.windows", _PLATFORM)
    docker.run_in(
        docker.Lane(r.name, image, _PLATFORM, "release-win", "win-stage"), _script(r, targets)
    )

    # The setup exe packs this same exe, so a clean exe means a clean setup.
    for arch, _ in targets:
        inspect.refuse(f"{_STAGE}/{r.name}-{arch}.exe")
        for daemon in r.daemons:
            inspect.refuse(f"{_STAGE}/{daemon.name}-{arch}.exe")
    for arch, _ in targets:
        setup = f"dist/{r.artifact(f'windows-{arch}-setup.exe')}"
        bare = f"dist/{r.artifact(f'windows-{arch}.exe')}"
        shutil.copyfile(f"{_STAGE}/{r.name}-{arch}-setup.exe", setup)
        shutil.copyfile(f"{_STAGE}/{r.name}-{arch}.exe", bare)
        r.sign([bare])
        print(f"built {setup}")
        print(f"built {bare}")
        for daemon in r.daemons:
            daemon_bare = f"dist/{daemon.artifact(f'windows-{arch}.exe')}"
            shutil.copyfile(f"{_STAGE}/{daemon.name}-{arch}.exe", daemon_bare)
            r.sign([daemon_bare])
            print(f"built {daemon_bare}")
    return 0


if __name__ == "__main__":
    run_main(main)
