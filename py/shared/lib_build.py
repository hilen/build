# The Rust lib of an iOS or tvOS build. It builds here when cargo is here, or on a
# mac builder through far, and then comes back so Xcode here links it. A shipped
# build gets the session key and the release mark, and is checked for the
# inspect server.

import os
from collections.abc import Sequence
from typing import TYPE_CHECKING

from shared import inspect, secrets
from shared.run import has, run, run_with_input

if TYPE_CHECKING:
    from shared.config import Config


def build(app: Config, line: str, fetch: Sequence[str], checked: str):
    # A host CFLAGS leaks into the cross build and breaks the C parts.
    os.environ.pop("CFLAGS", None)
    os.environ.pop("CXXFLAGS", None)
    release = inspect.is_release()
    key = secrets.session_key(app) if release else None
    if key is not None:
        # Read by the build here, and by the output mask of the far job.
        os.environ[secrets.SESSION_KEY_ENV] = key
    if has("cargo"):
        run(line if key is None else secrets.masked(line))
    else:
        # far does not pass the environment on, a shipped build gets its marks in
        # the job itself.
        if key is not None:
            run_with_input(secrets.far_job(line, key), key)
        elif release:
            run(secrets.far_job(line, None))
        else:
            run(f"far --on mac '{line}'")
        for path in fetch:
            run(f"far --on mac get {path}")
    # A test build of demo carries the inspect server on purpose, only a shipped
    # build is checked.
    if inspect.is_release():
        inspect.refuse(checked)
