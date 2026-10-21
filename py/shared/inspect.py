# Keeps the hilen inspect server out of every shipped build. The server lets
# anyone on the network read and drive the app. The engine build script stops a
# build that has the `inspect` feature while HILEN_RELEASE is set, and `refuse`
# checks the built file itself, which also catches a build that never set the
# mark.

import os
import subprocess
from typing import Final

from shared.util import bail

# The engine build script refuses the `inspect` feature while this is set.
RELEASE_ENV: Final = "HILEN_RELEASE"

# `MARKER` of hilen/src/inspect/mod.rs in 2 pieces, so no copy of this code ever
# matches its own scan.
_MARKER_PARTS: Final = ("hilen-inspect-", "server-compiled-in")
_FOUND: Final = 0
_NOT_FOUND: Final = 1


# Marks this process and every command it starts as a shipped build. The wrapper
# with-secrets.sh sets the same mark, this covers a run without it.
def mark_release():
    os.environ[RELEASE_ENV] = "1"


def is_release() -> bool:
    return bool(os.environ.get(RELEASE_ENV, ""))


def _scan(path: str) -> subprocess.CompletedProcess[bytes]:
    marker = "".join(_MARKER_PARTS)
    return subprocess.run(
        ["grep", "-r", "-l", "-a", "-F", "--", marker, path], capture_output=True, check=False
    )


def _scan_error(path: str, out: subprocess.CompletedProcess[bytes]) -> str:
    return f"could not scan {path} for the inspect server: {out.stderr.decode().strip()}"


# Whether the file at `path` carries the inspect server. An iOS app with it needs
# the local network keys in its `Info.plist`.
def has_server(path: str) -> bool:
    out = _scan(path)
    if out.returncode not in {_FOUND, _NOT_FOUND}:
        bail(_scan_error(path, out))
    return out.returncode == _FOUND


# Fails when the file at `path`, or any file under a folder, carries the inspect
# server. Call it on the built binary before anything is signed, packed or copied
# to dist.
def refuse(path: str):
    out = _scan(path)
    match out.returncode:
        case code if code == _NOT_FOUND:
            print(f"{path} has no inspect server")
        case code if code == _FOUND:
            bail(
                f"{out.stdout.decode().strip()} carries the hilen inspect server, refusing to ship "
                "it. Build without the `inspect` feature, see docs/inspect.md in the hilen repo."
            )
        case _:
            bail(_scan_error(path, out))
