# The export of an archived Apple app and its upload to App Store Connect, the
# same for iOS and tvOS.

import os
from pathlib import Path
from typing import Final

from shared.run import capture, run
from shared.util import bail

# The Gebling Games Studio Infisical project, it holds the Apple upload secret.
_INFISICAL_PROJECT: Final = "e2dd64d9-130c-4072-bd3d-0a98331364cb"
_UPLOAD_LOG: Final = "build/upload.log"


# The IPA step shells out to rsync, and Xcode only works with Apple's own. A newer
# rsync earlier on PATH, from nix or homebrew, makes the export die with a bare
# "Copy failed", the real cause shows only in the xcdistributionlogs bundle. The
# system paths go first for that. allowProvisioningUpdates lets xcodebuild mint
# the Apple Distribution certificate and the App Store profile for an app built
# here the first time, otherwise the export fails with "No profiles were found".
def export(archive_path: str):
    run(
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin:$PATH "
        f'xcodebuild -exportArchive -archivePath "{archive_path}" '
        '-exportOptionsPlist "export.plist" -exportPath "build" -allowProvisioningUpdates'
    )
    print("export: OK")


# The password stays a shell variable, so it never shows in the echoed command.
# altool exits 0 even when App Store Connect refuses the build, so its output is
# kept and read. A refused upload once printed "upload: OK".
def upload(ipa_path: str, kind: str):
    os.environ["APPLE_APP_SPECIFIC_PASSWORD"] = capture(
        f"infisical secrets get APPLE_APP_SPECIFIC_PASSWORD --projectId {_INFISICAL_PROJECT} "
        "--env prod --plain --silent"
    )
    run(
        f'xcrun altool --upload-app -f "{ipa_path}" -u 146100@gmail.com '
        f'-p "$APPLE_APP_SPECIFIC_PASSWORD" --type {kind} 2>&1 | tee {_UPLOAD_LOG}'
    )
    output = Path(_UPLOAD_LOG).read_text(encoding="utf-8", errors="replace")
    succeeded = "UPLOAD SUCCEEDED" in output or "No errors uploading" in output
    if "UPLOAD FAILED" in output or not succeeded:
        bail("upload failed, see the altool output above")
    print("upload: OK")
