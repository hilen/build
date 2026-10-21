#!/usr/bin/env -S uv run -q --no-dev

# Frees disk space on a GitHub linux runner before a large build.

import sys
from typing import Final

from shared.run import run, run_allow_fail
from shared.util import run_main

# uv sits in the runner tool cache and must survive this step.
_PATHS: Final = (
    "/usr/share/dotnet",
    "/opt/ghc",
    "/usr/local/share/boost",
    "/usr/local/lib/android",
    "/__t/CodeQL",
)


def main() -> int:
    if sys.platform == "darwin":
        return 0
    run("sudo df -h")
    for path in _PATHS:
        run_allow_fail(f'sudo rm -rf "{path}"')
    run("sudo df -h")
    return 0


if __name__ == "__main__":
    run_main(main)
