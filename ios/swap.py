#!/usr/bin/env -S uv run -q --no-dev

# 1 loader app in the iOS simulator or in the Apple TV simulator that swaps
# between several apps, `make swap`. See docs/hot-reload.md in hilen.
#
# Every command returns, so a person and an agent use it the same way.

import sys
from pathlib import Path
from typing import Final

from shared.device import Device
from shared.hot import System
from shared.swap import Swap
from shared.util import bail, run_main

_USAGE: Final = """swap between apps in 1 process of the iOS simulator

  start <folder> <folder>..   build every app, start the first one
  to <name>                   build the app again and swap to it
  status                      the app on the screen and what the process holds
  stop                        end the process

the same in the Apple TV simulator, with the word tv in front:

  tv start <folder> <folder>..
  tv to <name>
  tv status
  tv stop

on a real device `make device` in the folder of an app does all of this by
itself. The words here stay for a run from the engine repo, `phone` is the
paired iPhone and `tv device` the paired Apple TV:

  phone install               build the loader with the app of this repo, install and start it
  phone <folder>              build the app and swap the phone to it
  phone status                the library the loader on the phone runs
  tv device install | <folder> | status

A folder is the folder of the app crate. A name is its cargo package."""


def _on_device(swap: Swap, system: System, word: str):
    kind = "appleTV" if system is System.TVOS else "iPhone"
    device = Device.pick(Path.cwd(), kind)
    match word:
        case "install":
            swap.device_install(device)
        case "status":
            swap.device_status(device)
        case folder:
            swap.device_to(folder, device)


def main() -> int:
    args = sys.argv[1:]
    system = System.take(args)
    command = args[0] if args else ""
    swap = Swap.new(system)
    tv = system is System.TVOS
    match command, len(args):
        case "start", n if n > 1:
            swap.start(args[1:])
        case "to", 2:
            swap.to(args[1])
        case "status", 1:
            swap.status()
        case "stop", 1:
            swap.stop()
        case (("phone" | "device"), 2) if (command == "device") == tv:
            _on_device(swap, system, args[1])
        case _:
            print(_USAGE)
            bail("no such command")
    return 0


if __name__ == "__main__":
    run_main(main)
