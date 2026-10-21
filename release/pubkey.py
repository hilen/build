#!/usr/bin/env -S uv run -q --no-dev

# Prints the public half of the update key of the app as hex, the value that goes
# into assets/update-key.pub and that sign.py checks the signing key against.

from shared.update_key import public_hex, signing_key
from shared.util import run_main

from shared import release


def main() -> int:
    print(public_hex(signing_key(release.read().name)))
    return 0


if __name__ == "__main__":
    run_main(main)
