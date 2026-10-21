#!/usr/bin/env -S uv run -q --no-dev

# Builds the static ffmpeg archive for x86_64 Windows, the twin of ffmpeg.py for
# the 1 target that is not built on its own host. It cross builds in docker with
# clang in cl mode and the MSVC SDK from xwin, the same kind of build the Windows
# release of an app is, so the archive links there. The result in dist/ goes to a
# release of this repo like the others, see docs/video.md in hilen. The versions
# have to match ffmpeg.py.

from pathlib import Path
from typing import Final

from shared.run import run
from shared.util import run_main

_VERSION: Final = "9.0"
_DAV1D: Final = "1.5.4"
_ZLIB: Final = "1.3.1"


def main() -> int:
    out = Path.cwd() / "dist"
    out.mkdir(exist_ok=True)
    run("docker build -t hilen-ffmpeg-win build/ffmpeg-win")
    build = f"/opt/build.sh {_VERSION} {_DAV1D} {_ZLIB}"
    run(f'docker run --rm -v "{out}:/out" hilen-ffmpeg-win {build}')
    print(f"dist/ffmpeg-{_VERSION}-x86_64-pc-windows-msvc.tar.gz")
    return 0


if __name__ == "__main__":
    run_main(main)
