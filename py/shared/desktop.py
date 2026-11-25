# The release build of a desktop app with a login, with the real HILEN_SESSION_KEY
# of its Infisical project. A build without the key seals the stored login with a
# public development key.
#
# The build is not marked as a release, so the inspect server of a dev build
# still works. On a machine with no Rust toolchain the build runs on a far
# builder of the same system and the binary comes back.

import os
import sys
from collections.abc import Sequence

from shared import config, secrets
from shared.run import has, run, run_with_input
from shared.secrets import SESSION_KEY_ENV


def _system() -> str:
    match sys.platform:
        case "darwin":
            return "mac"
        case "win32":
            return "windows"
        case _:
            return "linux"


# Builds the binary of the app in the current folder and gives its path,
# relative to that folder. The arguments go to cargo, like `--features dev`.
def build_release(cargo_args: Sequence[str]) -> str:
    app = config.read()
    build = f"cargo build --release -p {app.app_name} {' '.join(cargo_args)}"
    binary = f"target/release/{app.app_name}"
    key = secrets.session_key(app)
    if key is None:
        print("no infisical_project in hilen.toml, the build uses the development session key")
    else:
        # Read by the build here, and by the output mask.
        os.environ[SESSION_KEY_ENV] = key
    if has("cargo"):
        run(build if key is None else secrets.masked(build))
        return binary
    system = _system()
    # The key goes in on stdin, so the job line and the far log never hold it.
    if key is None:
        run(f"far --on {system} '{build}'")
    else:
        job = (
            f"far --on {system} 'read -r {SESSION_KEY_ENV} && export {SESSION_KEY_ENV} && {build}'"
        )
        run_with_input(secrets.masked(job), key)
    run(f"far --on {system} get {binary}")
    return binary
