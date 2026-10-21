#!/usr/bin/env -S uv run -q --no-dev

# The Linux release, built in docker so the output is the same on a dev box and
# on a runner. 1 arch per run, `--arch=x64|aarch64`, the arch of the host by
# default. Outputs in dist/:
#   <name>-<v>-linux-<arch>.deb        first install, updates through apt
#   <name>-<v>-linux-<arch>.AppImage   signed, updates itself in place
#   <name>-<v>-linux-<triple-arch>     the bare binary, signed for the manifest
#   <daemon>-<v>-linux-<triple-arch>   each daemon of `daemons`, bare and signed

import platform
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from shared.util import bail, run_main

from shared import docker, inspect, links, release

if TYPE_CHECKING:
    from shared.release import Release

# target/release-linux is a docker volume, so everything the host writes for the
# container or reads back lives in a sibling folder.
_STAGE: Final = "target/linux-stage"


def _host_arch() -> str:
    return "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"


# linuxdeploy wants the icon file named after the Icon of the desktop entry.
def _write_desktop_file(r: Release):
    shutil.copyfile("assets/icon.png", f"{_STAGE}/{r.name}.png")
    Path(f"{_STAGE}/{r.name}.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={r.name}\n"
        f"{links.desktop_lines(r.bin, r.link_scheme)}"
        f"Icon={r.name}\n"
        "Categories=Development;\n"
        "Terminal=false\n",
        encoding="utf-8",
    )


def _script(r: Release) -> str:
    lines = [
        "set -euo pipefail",
        f"cargo build --locked --release -p {r.name} --bin {r.bin}",
        f"BIN=target/release-linux/release/{r.bin}",
        f"OUT={_STAGE}/out",
        "rm -rf $OUT /tmp/out && mkdir -p $OUT /tmp/out",
        f"cargo deb -p {r.name} --no-build --no-strip -o $OUT/{r.name}.deb",
        "cd /tmp/out",
        (
            f"linuxdeploy --appdir AppDir -e /work/apps/app/$BIN "
            f"-d /work/apps/app/{_STAGE}/{r.name}.desktop -i /work/apps/app/{_STAGE}/{r.name}.png "
            "--output appimage"
        ),
        "cd /work/apps/app",
        f"cp /tmp/out/{r.name}-*.AppImage $OUT/{r.name}.AppImage",
        f"cp $BIN $OUT/{r.name}",
    ]
    # A daemon is only its bare binary, built in the same container.
    for daemon in r.daemons:
        lines.append(f"cargo build --locked --release -p {daemon.name} --bin {daemon.bin}")
        lines.append(f"cp target/release-linux/release/{daemon.bin} $OUT/{daemon.name}")
    return "\n".join(lines)


def main() -> int:
    inspect.mark_release()
    r = release.read()
    arch = next((a.removeprefix("--arch=") for a in sys.argv[1:] if a.startswith("--arch=")), None)
    arch = arch or _host_arch()
    match arch:
        case "x64":
            target_platform, rust_arch = "linux/amd64", "x86_64"
        case "aarch64":
            target_platform, rust_arch = "linux/arm64", "aarch64"
        case other:
            bail(f"unknown arch {other}, use x64 or aarch64")
    Path("dist").mkdir(exist_ok=True)
    Path(_STAGE).mkdir(parents=True, exist_ok=True)
    _write_desktop_file(r)

    image = f"{r.name}-linux-builder"
    docker.build_image(image, "Dockerfile.linux", target_platform)
    lane = docker.Lane(r.name, image, target_platform, "release-linux", "linux-stage")
    docker.run_in(lane, _script(r))

    out = f"{_STAGE}/out"
    # The .deb and the AppImage pack this same binary.
    inspect.refuse(f"{out}/{r.name}")
    deb = f"dist/{r.artifact(f'linux-{arch}.deb')}"
    appimage = f"dist/{r.artifact(f'linux-{arch}.AppImage')}"
    bare = f"dist/{r.artifact(f'linux-{rust_arch}')}"
    shutil.copyfile(f"{out}/{r.name}.deb", deb)
    shutil.copyfile(f"{out}/{r.name}.AppImage", appimage)
    shutil.copyfile(f"{out}/{r.name}", bare)
    r.sign([bare, appimage])
    for file in (deb, appimage, bare):
        print(f"built {file}")
    for daemon in r.daemons:
        inspect.refuse(f"{out}/{daemon.name}")
        daemon_bare = f"dist/{daemon.artifact(f'linux-{rust_arch}')}"
        shutil.copyfile(f"{out}/{daemon.name}", daemon_bare)
        r.sign([daemon_bare])
        print(f"built {daemon_bare}")
    return 0


if __name__ == "__main__":
    run_main(main)
