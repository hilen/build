#!/usr/bin/env -S uv run -q --no-dev

# Builds, archives, exports and uploads the tvOS app to App Store Connect.

import os
import sys

from shared.run import run
from shared.util import run_main

from shared import apple_upload, config


def main() -> int:
    app = config.read()
    run(f"uv run -q --no-dev ./build/tvos/build-project.py {' '.join(sys.argv[1:])}".strip())
    os.environ.pop("CFLAGS", None)
    os.environ.pop("CXXFLAGS", None)
    archive_path = f"build/{app.project_name}.xcarchive"
    ipa_path = f"build/{app.bundle_name()}.ipa"
    os.chdir("mobile/tvOS")
    print("codesign identity:")
    run("security find-identity -p codesigning -v")
    # The archive is not signed. A signed one wants a development profile, and
    # Apple makes none for a team with no Apple TV registered: "Your team has no
    # devices from which to generate a provisioning profile". The export below
    # signs for the store, which needs no device.
    run(
        f'xcodebuild -project "{app.project_name}".xcodeproj -scheme "{app.project_name}" '
        f'-sdk appletvos -configuration Release archive -archivePath "{archive_path}" '
        "CODE_SIGNING_ALLOWED=NO"
    )
    print("build: OK")
    apple_upload.export(archive_path)
    apple_upload.upload(ipa_path, "appletvos")
    return 0


if __name__ == "__main__":
    run_main(main)
