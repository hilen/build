# The ci-signing keychain has its own password, so it is locked after every login,
# and a codesign that meets it shows a password dialog. Unlock it before signing.

from pathlib import Path
from typing import Final

from shared.run import run_secret

_KEYCHAIN: Final = Path.home() / "Library/Keychains/ci-signing.keychain-db"
_PROJECT: Final = "e2dd64d9-130c-4072-bd3d-0a98331364cb"
_INFISICAL_NAME: Final = "APPLE_CI_KEYCHAIN_PASSWORD"


def unlock_signing_keychain():
    if not _KEYCHAIN.is_file():
        return
    run_secret(
        f"password=$(infisical secrets get {_INFISICAL_NAME} --projectId {_PROJECT} --env prod "
        f'--plain --silent) && security unlock-keychain -p "$password" "{_KEYCHAIN}"'
    )
