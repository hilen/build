#!/usr/bin/env -S uv run -q --no-dev

# The load test on a real device, `make load-test` for the paired iPhone and
# `make load-test args="tv"` for the paired Apple TV. See "What iOS allows" in
# docs/hot-reload.md in hilen. Run from the hilen repo.
#
# Builds a tiny app with the bundle id of this repo as a development build,
# installs it and starts it. The app copies 1 library with 3 kinds of signature
# into its data folder, loads each and prints what the system said. A hot swap
# on a device needs the last of the 3 to load.

import sys
from typing import Final

from shared.hot import System, development_profile, paired, sign_identity
from shared.run import run
from shared.util import run_main

from shared import config

_NATIVE: Final = "hilen/native/ios"
_EXECUTABLE: Final = "LoadTest"


def _step(message: str):
    print(f"\n[load-test] {message}", flush=True)


def main() -> int:
    system = System.take(sys.argv[1:])
    bundle_id = config.read().bundle_id
    if system is System.IOS:
        folder, sdk, target, plist = (
            "target/hot/load-test",
            "iphoneos",
            "arm64-apple-ios14.0",
            "hot_loader.plist",
        )
    else:
        folder, sdk, target, plist = (
            "target/hot/tv/load-test",
            "appletvos",
            "arm64-apple-tvos15.0",
            "hot_loader_tvos.plist",
        )
    app = f"{folder}/{_EXECUTABLE}.app"
    profile = development_profile(bundle_id, system)
    identity = sign_identity()
    clang = f"xcrun -sdk {sdk} clang -target {target}"

    _step("building the app and the 3 libraries")
    run(f"rm -rf {folder} && mkdir -p {app}/libs")
    run(f"{clang} -dynamiclib {_NATIVE}/load_test_lib.c -o {folder}/lib.dylib")
    # The linker signs an arm64 library ad hoc by itself.
    run(
        f"cp {folder}/lib.dylib {app}/libs/none.bin && "
        f"codesign --remove-signature {app}/libs/none.bin"
    )
    run(f"cp {folder}/lib.dylib {app}/libs/adhoc.bin && codesign -s - --force {app}/libs/adhoc.bin")
    run(
        f"cp {folder}/lib.dylib {app}/libs/development.bin && "
        f"codesign -s {identity} --force {app}/libs/development.bin"
    )
    run(
        f"sed -e s/HILEN_EXECUTABLE/{_EXECUTABLE}/g -e s/HILEN_BUNDLE_ID/{bundle_id}/g "
        f"{_NATIVE}/{plist} > {app}/Info.plist"
    )
    run(
        f"{clang} -fobjc-arc -Wall {_NATIVE}/load_test.m -framework UIKit -framework Foundation "
        f"-o {app}/{_EXECUTABLE}"
    )
    run(f'cp "{profile}" {app}/embedded.mobileprovision')
    run(
        f'security cms -D -i "{profile}" | plutil -extract Entitlements xml1 '
        f"-o {folder}/entitlements.plist -"
    )
    run(f"codesign -s {identity} --force --entitlements {folder}/entitlements.plist {app}")

    _step("installing and starting it")
    device = paired(system)
    run(f"xcrun devicectl device install app --device {device} {app}")
    run(
        f"xcrun devicectl device process launch --device {device} --console "
        f"--terminate-existing {bundle_id}"
    )
    return 0


if __name__ == "__main__":
    run_main(main)
