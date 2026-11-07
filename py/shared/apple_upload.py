# The export of an archived Apple app and its upload to App Store Connect, the
# same for iOS and tvOS.

import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from shared.run import capture, run
from shared.util import ScriptError

# The Gebling Games Studio Infisical project, it holds the App Store Connect key.
_INFISICAL_PROJECT: Final = "e2dd64d9-130c-4072-bd3d-0a98331364cb"
_KEY_ID: Final = "APPLE_ASC_KEY_ID"
_ISSUER_ID: Final = "APPLE_ASC_ISSUER_ID"
_KEY_P8: Final = "APPLE_ASC_KEY_P8"
_UPLOAD_LOG: Final = "build/upload.log"


@dataclass(frozen=True, slots=True)
class ApiKey:
    key_id: str
    issuer_id: str
    path: Path

    def xcodebuild_flags(self) -> str:
        return (
            f'-authenticationKeyPath "{self.path}" -authenticationKeyID {self.key_id} '
            f"-authenticationKeyIssuerID {self.issuer_id}"
        )


def _secret(name: str) -> str:
    return capture(
        f"infisical secrets get {name} --projectId {_INFISICAL_PROJECT} --env prod --plain --silent"
    )


# The Apple ID of Xcode is not used. macOS Sequoia drops it from Xcode within a
# day, and the export then fails with "No Accounts". The key file lives only in
# a private temp folder while the block runs.
@contextmanager
def api_key() -> Generator[ApiKey]:
    key_id = _secret(_KEY_ID)
    issuer_id = _secret(_ISSUER_ID)
    p8 = _secret(_KEY_P8)
    if not key_id or not issuer_id or not p8:
        msg = (
            f"{_KEY_ID}, {_ISSUER_ID} and {_KEY_P8} must be set in the prod env of "
            f"Infisical project {_INFISICAL_PROJECT}"
        )
        raise ScriptError(msg)
    folder = Path(tempfile.mkdtemp(prefix="asc-key-"))
    try:
        path = folder / f"AuthKey_{key_id}.p8"
        path.write_text(f"{p8}\n", encoding="utf-8")
        path.chmod(0o600)
        yield ApiKey(key_id, issuer_id, path)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# The IPA step shells out to rsync, and Xcode only works with Apple's own. A newer
# rsync earlier on PATH, from nix or homebrew, makes the export die with a bare
# "Copy failed", the real cause shows only in the xcdistributionlogs bundle. The
# system paths go first for that. allowProvisioningUpdates lets xcodebuild mint
# the Apple Distribution certificate and the App Store profile for an app built
# here the first time, otherwise the export fails with "No profiles were found".
def export(archive_path: str, key: ApiKey):
    run(
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin:$PATH "
        f'xcodebuild -exportArchive -archivePath "{archive_path}" '
        '-exportOptionsPlist "export.plist" -exportPath "build" -allowProvisioningUpdates '
        f"{key.xcodebuild_flags()}"
    )
    print("export: OK")


# altool exits 0 even when App Store Connect refuses the build, so its output is
# kept and read. A refused upload once printed "upload: OK".
def upload(ipa_path: str, kind: str, key: ApiKey):
    run(
        f'xcrun altool --upload-app -f "{ipa_path}" --type {kind} '
        f'--api-key {key.key_id} --api-issuer {key.issuer_id} --p8-file-path "{key.path}" '
        f"2>&1 | tee {_UPLOAD_LOG}"
    )
    output = Path(_UPLOAD_LOG).read_text(encoding="utf-8", errors="replace")
    succeeded = "UPLOAD SUCCEEDED" in output or "No errors uploading" in output
    if "UPLOAD FAILED" in output or not succeeded:
        msg = "upload failed, see the altool output above"
        raise ScriptError(msg)
    print("upload: OK")
