#!/usr/bin/env -S uv run -q --no-dev

# Unlocks the signing keychain of this Mac before a codesign with the
# Developer ID, so no password dialog comes up, see shared/keychain.py.

from shared.keychain import unlock_signing_keychain
from shared.util import run_main


def main() -> int:
    unlock_signing_keychain()
    return 0


if __name__ == "__main__":
    run_main(main)
