#!/usr/bin/env -S uv run -q --no-dev

# Hot reload of the app in the iOS simulator, `make hot`, or in the Apple TV
# simulator, `make hot args="tv"`. See docs/hot-reload.md in hilen.
#
# Builds the app as 1 dynamic library, starts the loader app in the simulator of
# this Mac, then watches the sources. Every saved file is a new build, and the
# running app swaps to it with no install and no restart.

import sys
import time
from typing import Final

from shared.hot import Hot, System
from shared.util import ScriptError, run_main

from shared import config

_POLL: Final = 0.3


def _step(message: str):
    print(f"\n[hot] {message}", flush=True)


def main() -> int:
    app = config.read()
    hot = Hot.new(app).for_system(System.take(sys.argv[1:]))
    _step("building the library")
    hot.publish(hot.build_library(app.app_name, ""), None)
    _step("building the loader")
    loader = hot.build_loader()
    _step("starting the app")
    device = hot.simulator()
    pid = hot.launch(device, loader)
    _step(f"{hot.bundle_id} runs as process {pid}. A saved file reloads it, Ctrl-C ends.")

    sources = hot.sources()
    while True:
        time.sleep(_POLL)
        now = hot.sources()
        if now == sources:
            continue
        sources = now
        started = time.monotonic()
        try:
            library = hot.build_library(app.app_name, "")
        except ScriptError as err:
            # The loader has no new file to load, the app keeps its code.
            _step(f"the build failed, the app keeps the old code: {err}")
            continue
        name = hot.publish(library, None)
        _step(f"{name} is out after {time.monotonic() - started:.1f} s")


if __name__ == "__main__":
    run_main(main)
