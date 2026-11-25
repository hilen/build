#!/usr/bin/env -S uv run -q --no-dev

# The build of `make run` without the start, for an app that starts its binary
# another way, like as a signed bundle in /Applications. The binary is built
# with the real HILEN_SESSION_KEY, see shared/desktop.py. The arguments go to
# cargo.

import sys

from shared.desktop import build_release
from shared.util import run_main


def main() -> int:
    build_release(sys.argv[1:])
    return 0


if __name__ == "__main__":
    run_main(main)
