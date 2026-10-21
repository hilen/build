# The session key a shipped phone build bakes in. The engine seals the stored
# login with it, see SessionStore in hilen. A release build of an app with a
# login fails in the engine build script when the key is missing, so a phone
# never ships the public development key.

import os
from typing import TYPE_CHECKING, Final

from shared.inspect import RELEASE_ENV
from shared.run import capture
from shared.util import ScriptError, bail

if TYPE_CHECKING:
    from shared.config import Config

SESSION_KEY_ENV: Final = "HILEN_SESSION_KEY"


# The key from the environment, set by with-secrets.sh, or else from the
# Infisical project that hilen.toml names. None when neither is there, an app
# with no login needs no key.
def session_key(config: Config) -> str | None:
    key = os.environ.get(SESSION_KEY_ENV, "")
    if key:
        return key
    project = config.infisical_project
    if project is None:
        return None
    try:
        key = capture(
            f"infisical secrets get {SESSION_KEY_ENV} --projectId {project} --env prod "
            "--plain --silent"
        )
    except ScriptError as err:
        bail(f"{SESSION_KEY_ENV} was not read from Infisical project {project}: {err}")
    if not key:
        bail(f"{SESSION_KEY_ENV} is empty in Infisical project {project}")
    return key


# The far job that builds a shipped lib. The key goes in on stdin, so the job
# line, the far log and the process list never hold it.
def far_job(build: str, key: str | None) -> str:
    if key is None:
        return f"far --on mac 'export {RELEASE_ENV}=1 && {build}'"
    return masked(
        f"far --on mac 'read -r {SESSION_KEY_ENV} && export {SESSION_KEY_ENV} "
        f"{RELEASE_ENV}=1 && {build}'"
    )


# Runs `cmd` with its output filtered. cargo lipo prints the whole environment of
# a failed build, the key with it. awk takes the key from its environment, so it
# is on no command line either. The caller puts the key into the environment of
# this process first.
def masked(cmd: str) -> str:
    return (
        f'set -o pipefail; {cmd} 2>&1 | awk \'{{ k = ENVIRON["{SESSION_KEY_ENV}"]; '
        'if (k != "") gsub(k, "[hidden]"); print; fflush() }\''
    )
