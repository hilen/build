#!/usr/bin/env -S uv run -q --no-dev

# Runs the app of this folder on a paired iPhone, iPad or Apple TV as a hot
# build, `make device`. See docs/hot-reload.md in hilen.
#
# The device runs a loader app, installed once. This command builds the app as 1
# dynamic library and sends it over the network, and the loader swaps to it with
# no install. Nothing watches the sources, a new build goes out on the next call.

import sys
from pathlib import Path
from typing import Final

from shared.make_device import make_device
from shared.util import bail, run_main

_USAGE: Final = """run the app of this folder on a paired iPhone, iPad or Apple TV

  make device                  build the app and swap the device to it
  make device args=status      the library the loader on the device runs
  make device args=install     build the loader, install it and start it, once per device
  make device args=release     free the loader of the device for another session

Only 1 agent session at a time sends apps to a device. Another session is
refused until the holder stops or releases it, a person always gets it.

A word in front picks the device by a part of its name or kind, like
args=tv or args="ipad install". The next call with no word goes to the
same device."""

_COMMANDS: Final = ("install", "status", "release")


def main() -> int:
    args = sys.argv[1:]
    command = args.pop() if args and args[-1] in _COMMANDS else None
    if len(args) > 1 or (args and args[0].startswith("-")):
        print(_USAGE)
        bail("no such command")
    make_device(Path.cwd(), args[0] if args else None, command)
    return 0


if __name__ == "__main__":
    run_main(main)
