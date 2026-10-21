#!/usr/bin/env -S uv run -q --no-dev

# The hot reload lane of hilen, `make hot-test`, and `make hot-test args="tv"` for
# the Apple TV simulator. See docs/hot-reload.md there.
#
# Builds the `hot-test` app 2 times as a dynamic library, the second time as the
# same app after a change. It starts the first through the loader, then swaps the
# 2 several times in the 1 running process. After every swap it checks that the
# new code runs, that the screen shows it, that the process is still the same,
# and that no thread of an old library stayed behind.

import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from shared.hot import Hot, System, is_alive, screen_color, thread_count
from shared.run import run_quiet
from shared.util import bail, run_main

_PACKAGE: Final = "hot-test"
_EXECUTABLE: Final = "HotTest"
_BUNDLE_ID: Final = "hilen.hot-test"
_MARKER: Final = "hot-generation"
_RELOADS: Final = 6
_COLOR_TRIES: Final = 20
_COLOR_POLL: Final = 0.25


# What a build leaves behind when it runs.
@dataclass(frozen=True, slots=True)
class _Build:
    name: str
    feature: str
    color: tuple[int, int, int]


_FIRST: Final = _Build("first", "", (255, 0, 0))
_SECOND: Final = _Build("second", ",second", (0, 255, 0))


def _step(message: str):
    print(f"\n[hot-test] {message}", flush=True)


# The library that was put out runs, shows on the screen, and the process is the
# one the loader started.
def _check(hot: Hot, device: str, pid: int, build: _Build):
    hot.wait_for_marker(device, _MARKER, build.name)
    if not is_alive(pid):
        bail(f"process {pid} is gone, the app did not survive the {build.name} library")
    # The marker is written before the first frame is out.
    color = (0, 0, 0)
    for _ in range(_COLOR_TRIES):
        color = screen_color(device)
        if color == build.color:
            return
        time.sleep(_COLOR_POLL)
    bail(f"the screen shows {color}, the {build.name} library draws {build.color}")


def _swap(hot: Hot, device: str, loader: Path, first: Path, second: Path):
    pid = hot.launch(device, loader)
    _check(hot, device, pid, _FIRST)
    threads: list[int] = []
    for reload in range(1, _RELOADS + 1):
        build, library = (_SECOND, second) if reload % 2 == 1 else (_FIRST, first)
        _step(f"reload {reload}, the {build.name} library")
        hot.publish(library, None)
        _check(hot, device, pid, build)
        threads.append(thread_count(pid))
    print(f"[hot-test] threads after each reload: {threads}")
    # The first reloads can still start a thread that every later library reuses,
    # like one of the OS. From then on the count must not grow.
    settled = threads[1]
    last = threads[-1]
    if last > settled:
        bail(
            f"an old library left threads behind: {settled} after reload 2, "
            f"{last} after reload {_RELOADS}"
        )
    run_quiet(f"xcrun simctl terminate {device} {_BUNDLE_ID}")
    _step(f"ok: {_RELOADS} reloads in process {pid}")


def main() -> int:
    if sys.platform != "darwin":
        print("[hot-test] not macOS, skipping the hot reload lane.")
        return 0
    hot = Hot.named(_EXECUTABLE, _BUNDLE_ID).for_system(System.take(sys.argv[1:]))
    # Both builds land in the same file, so each is put aside.
    kept: dict[str, Path] = {}
    for build in (_SECOND, _FIRST):
        _step(f"building the {build.name} library")
        built = hot.build_library(_PACKAGE, build.feature)
        kept[build.name] = built.with_suffix(f".{build.name}")
        shutil.copyfile(built, kept[build.name])
    _step("building the loader")
    loader = hot.build_loader()
    _step("starting the first library")
    hot.publish(kept["first"], None)
    device = hot.simulator()
    try:
        _swap(hot, device, loader, kept["first"], kept["second"])
    finally:
        hot.release_device(device)
    return 0


if __name__ == "__main__":
    run_main(main)
