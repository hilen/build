#!/usr/bin/env -S uv run -q --no-dev

# Builds the app with a profile and records it with samply, `make profile`.

import sys

from shared.run import run
from shared.util import run_main

from shared import config


def main() -> int:
    app = config.read()
    # The cargo profile to build. "dev" gives the fastest build and the worst
    # numbers, "release-debug" keeps the optimizations and the symbols samply
    # needs.
    profile = sys.argv[1] if len(sys.argv) > 1 else "release-debug"
    print(f"APP_NAME: {app.app_name}")
    print(f"profile: {profile}")
    run("cargo install --locked samply")
    run(f'cargo build -p "{app.app_name}" --profile="{profile}"')
    target_dir = "debug" if profile == "dev" else profile
    run(f"samply record ./target/{target_dir}/{app.app_name}")
    return 0


if __name__ == "__main__":
    run_main(main)
