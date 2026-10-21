#!/usr/bin/env -S uv run -q --no-dev

# Builds, archives, exports and uploads the iOS app to App Store Connect, `make
# fly`, then the tvOS app too when hilen.toml says `tvos = true`.

import os

from shared.run import run
from shared.util import run_main

from shared import apple_upload, config, inspect, ios


def main() -> int:
    app = config.read()
    # An upload is a shipped build: the lib gets the session key of the app and
    # the engine refuses the inspect server in it.
    inspect.mark_release()
    run("uv run -q --no-dev ./build/ios/build-project.py")
    os.environ.pop("CFLAGS", None)
    os.environ.pop("CXXFLAGS", None)
    archive_path = f"build/{app.project_name}.xcarchive"
    ipa_path = f"build/{app.bundle_name()}.ipa"
    os.chdir("mobile/iOS")
    print(f"PROJECT_NAME: {app.project_name}")
    print(f"ARCHIVE_PATH: {archive_path}")
    print(f"IPA_PATH: {ipa_path}")
    print("codesign identity:")
    run("security find-identity -p codesigning -v")

    # hilen-mobile makes the project again, so the linker flags go on the archive
    # command, see shared/ios.py for what they are. allowProvisioningUpdates is
    # needed here as well as on the export. The archive signs too, and it runs
    # first, so a bundle id never built on this machine dies here with "No
    # profiles were found" long before the export can mint one.
    run(
        f'xcodebuild -project "{app.project_name}".xcodeproj -scheme "{app.project_name}" '
        f'-sdk iphoneos -configuration Release archive -archivePath "{archive_path}" '
        f'OTHER_LDFLAGS="{ios.LDFLAGS}" -allowProvisioningUpdates'
    )
    print("build: OK")
    apple_upload.export(archive_path)
    apple_upload.upload(ipa_path, "ios")

    # The tvOS build goes up after the iOS one. Its project step makes the mobile
    # folder again, which the iOS upload no longer needs by now.
    if app.tvos:
        os.chdir("../..")
        run("uv run -q --no-dev ./build/tvos/flight.py")
    return 0


if __name__ == "__main__":
    run_main(main)
