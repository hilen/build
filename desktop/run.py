#!/usr/bin/env -S uv run -q --no-dev

# `make run` of a desktop app with a login: builds the release binary with the
# real HILEN_SESSION_KEY of its Infisical project and starts it, see
# shared/desktop.py. The arguments go to cargo, like `--features dev` for the
# inspect server.

import sys

from shared.desktop import build_release
from shared.run import run
from shared.util import run_main


def main() -> int:
    binary = build_release(sys.argv[1:])
    run(f"./{binary}")
    return 0


if __name__ == "__main__":
    run_main(main)
