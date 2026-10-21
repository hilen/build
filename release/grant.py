#!/usr/bin/env -S uv run -q --no-dev

# Prints the name of the upload grant of this app, `<deployment>-<folder>`, like
# `get-flixen`. door.sh sends the release files to beekeeper under that name, and
# beekeeper knows which folder of which deployment it stands for.

from shared.util import run_main

from shared import release


def main() -> int:
    found = release.read()
    print(f"{found.host_deployment}-{found.target_subdir.replace('/', '-')}")
    return 0


if __name__ == "__main__":
    run_main(main)
