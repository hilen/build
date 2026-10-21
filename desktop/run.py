#!/usr/bin/env -S uv run -q --no-dev

# `make run` of a desktop app with a login: builds the release binary with the
# real HILEN_SESSION_KEY of its Infisical project and starts it. A build without
# the key seals the stored login with a public development key. The arguments go
# to cargo, like `--features dev` for the inspect server.
#
# The build is not marked as a release, so the inspect server of a dev build
# still works. On a machine with no Rust toolchain the build runs on a far
# builder of the same system and the binary comes back.

import os
import sys

from shared.run import has, run, run_with_input
from shared.secrets import SESSION_KEY_ENV
from shared.util import run_main

from shared import config, secrets


def _system() -> str:
    match sys.platform:
        case "darwin":
            return "mac"
        case "win32":
            return "windows"
        case _:
            return "linux"


def main() -> int:
    app = config.read()
    build = f"cargo build --release -p {app.app_name} {' '.join(sys.argv[1:])}"
    binary = f"target/release/{app.app_name}"
    key = secrets.session_key(app)
    if key is None:
        print("no infisical_project in hilen.toml, the build uses the development session key")
    else:
        # Read by the build here, and by the output mask.
        os.environ[SESSION_KEY_ENV] = key
    if has("cargo"):
        run(build if key is None else secrets.masked(build))
    else:
        system = _system()
        # The key goes in on stdin, so the job line and the far log never hold it.
        if key is None:
            run(f"far --on {system} '{build}'")
        else:
            job = (
                f"far --on {system} 'read -r {SESSION_KEY_ENV} && export {SESSION_KEY_ENV} "
                f"&& {build}'"
            )
            run_with_input(secrets.masked(job), key)
        run(f"far --on {system} get {binary}")
    run(f"./{binary}")
    return 0


if __name__ == "__main__":
    run_main(main)
