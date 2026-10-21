#!/usr/bin/env -S uv run -q --no-dev

# Runs the UI suite on every lane and prints 1 summary at the end.
#
# Desktop debug and desktop release share the default cargo target, so they run
# 1 after another. The iOS simulator lane uses its own target folder and runs
# next to them on a thread of its own. Each lane streams its own output, the iOS
# lane on purpose quiet, and the counts are gathered into 1 table at the end.
#
# The full output of every lane also lands in target/ui-test/<lane>.log, and
# each failure report in target/ui-test/failures/<lane>/<test>.txt, so a failed
# run can be read back without running it again.

import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from shared.ui_report import LOG_DIR, Lane, desktop_lane, ios_lane, log_path
from shared.util import bail, run_main

_IOS: str = "iOS simulator"


# Streams the output of a command live, writes it to `log` and keeps it, so a
# lane stays watchable, lives on disk and its result line can still be read.
def tee(command: str, log: Path) -> tuple[str, bool]:
    output: list[str] = []
    with (
        log.open("w", encoding="utf-8") as file,
        subprocess.Popen(
            ["sh", "-c", f"{command} 2>&1"], stdout=subprocess.PIPE, text=True, errors="replace"
        ) as child,
    ):
        if child.stdout is None:
            bail("no output stream")
        for raw in child.stdout:
            line = raw.rstrip("\n")
            print(line, flush=True)
            file.write(f"{line}\n")
            output.append(f"{line}\n")
        code = child.wait()
    return "".join(output), code == 0


def _summary(lanes: list[Lane], *, is_mac: bool):
    width = max(len(lane.name) for lane in lanes)
    bar = "=" * (width + 26)
    print(f"\n{bar}")
    print("  UI tests")
    print(bar)
    for lane in lanes:
        if not is_mac and lane.name == _IOS:
            status = "skipped (not macOS)"
        else:
            status = f"{lane.passed} passed   {lane.failed} failed"
        print(f"  {lane.name:<{width}}   {status}")
    print(bar)
    for lane in lanes:
        print(f"  {lane.name:<{width}}   {lane.log}")
    failed = [lane for lane in lanes if lane.failures]
    if failed:
        print("\n  Failures")
        for lane in failed:
            for name, path in lane.failures:
                print(f"  {lane.name:<{width}}   {name} -> {path}")
    print(bar)


def main() -> int:
    is_mac = sys.platform == "darwin"
    # A fresh log folder per run, so a stale failure file never reads as current.
    shutil.rmtree(LOG_DIR, ignore_errors=True)
    Path(LOG_DIR).mkdir(parents=True)
    ios_log = log_path(_IOS)
    debug_log = log_path("desktop debug")
    release_log = log_path("desktop release")

    with ThreadPoolExecutor(max_workers=1) as pool:
        # The iOS lane starts first, so it builds and runs while the desktop
        # lanes go.
        ios = (
            pool.submit(
                tee, "HILEN_IOS_QUIET=1 uv run -q --no-dev ./build/ios/sim-test.py", ios_log
            )
            if is_mac
            else None
        )
        debug = tee("cargo run -p ui-test", debug_log)
        release = tee("cargo run -p ui-test --release", release_log)
        lanes = [
            desktop_lane("desktop debug", debug[0], ok=debug[1], log=debug_log),
            desktop_lane("desktop release", release[0], ok=release[1], log=release_log),
        ]
        if ios is None:
            lanes.append(Lane(_IOS, 0, 0, ok=True, log=ios_log, failures=()))
        else:
            output, ok = ios.result()
            lanes.append(ios_lane(output, ok=ok, log=ios_log))

    _summary(lanes, is_mac=is_mac)
    return 1 if any(not lane.ok for lane in lanes) else 0


if __name__ == "__main__":
    run_main(main)
