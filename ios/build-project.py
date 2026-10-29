#!/usr/bin/env -S uv run -q --no-dev

# Builds the Rust lib, makes the Xcode project with hilen-mobile, puts the
# settings of the app into it and builds it for the simulator.

import os
import subprocess
import sys

from shared.run import has, run
from shared.util import bail, run_main

from shared import biometric, camera, config, inspect, ios, local_network, mobile, speech, toml


def main() -> int:
    app = config.read()
    run("uv run -q --no-dev ./build/ios/build-lib.py")
    mobile.generate(sys.argv[1:])
    mobile.rewrite(
        f"mobile/iOS/{app.project_name}.xcodeproj/project.pbxproj",
        [("IPHONEOS_DEPLOYMENT_TARGET", app.ios_minimum_version)],
        lipo=not has("cargo"),
    )
    plist = f"mobile/iOS/{app.project_name}/Info.plist"
    # hilen-mobile bakes CFBundleShortVersionString 1.0 into the generated
    # Info.plist with no knob, so the real version goes in before the archive
    # reads it. From the repo root, before the chdir below.
    mobile.set_version(plist, app.version)
    ios.write_display_name(plist, app.display_name)

    # iOS stops an app that asks for the camera with no text to show, and fails a
    # Face ID check with none. The text goes past the shell, it is the own words
    # of the app.
    text = toml.read_text()
    for key, usage in (
        (camera.USAGE_KEY, camera.usage_of(text)),
        (biometric.USAGE_KEY, biometric.usage_of(text)),
        (speech.USAGE_KEY, speech.usage_of(text)),
    ):
        if usage is None:
            continue
        add = f"Add :{key} string {usage}"
        print(f"PlistBuddy {add}", flush=True)
        if (
            subprocess.run(["/usr/libexec/PlistBuddy", "-c", add, plist], check=False).returncode
            != 0
        ):
            bail(f"the usage text {key} did not go into {plist}")

    # An iPhone lets an app announce itself or browse on the local network only
    # for the types in these 2 keys, see docs/inspect.md in hilen. The inspect
    # server announces only in a build that carries it, a shipped app has only
    # the types of its [local_network] table.
    lib = f"target/universal/release/{app.lib_name}"
    local_network.write_plist(plist, app.local_network, inspect=inspect.has_server(lib))

    os.chdir("mobile/iOS")
    run("xcodebuild -showsdks")
    # An explicit destination fails with a clear "iOS is not installed" message
    # when the platform is missing. The -sdk flag instead falls back to a Mac
    # Catalyst destination and dies at link time with an arch mismatch.
    run(
        f'xcodebuild -scheme {app.project_name} -destination "generic/platform=iOS Simulator" '
        f'OTHER_LDFLAGS="{ios.LDFLAGS}" build'
    )
    return 0


if __name__ == "__main__":
    run_main(main)
