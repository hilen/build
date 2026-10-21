#!/usr/bin/env -S uv run -q --no-dev

# Builds the Rust libs, makes the Xcode project with hilen-mobile, puts the
# settings of the app into it and builds it for the simulator.

import os
import sys
from pathlib import Path

from shared.run import run
from shared.util import run_main

from shared import config, inspect, ios, local_network, mobile, tvos


def main() -> int:
    app = config.read()
    run("uv run -q --no-dev ./build/tvos/build-lib.py")
    mobile.generate(sys.argv[1:])

    # The template has a placeholder icon. An app keeps its own tvOS icon set,
    # the layered icon and the top shelf pictures, in
    # `assets/TVIcon.brandassets`, and it goes over the one of the template.
    own_icon = Path("assets/TVIcon.brandassets")
    if own_icon.is_dir():
        template = (
            f"mobile/tvOS/{app.project_name}/Assets.xcassets/App Icon & Top Shelf Image.brandassets"
        )
        run(f'rm -rf "{template}" && cp -R "{own_icon}" "{template}"')

    mobile.rewrite(
        f"mobile/tvOS/{app.project_name}.xcodeproj/project.pbxproj",
        [("TVOS_DEPLOYMENT_TARGET", app.tvos_minimum_version)],
        lipo=False,
    )
    plist = f"mobile/tvOS/{app.project_name}/Info.plist"
    mobile.set_version(plist, app.version)
    ios.write_display_name(plist, app.display_name)

    # An Apple TV lets an app announce itself or browse on the local network only
    # for the types in these 2 keys, see docs/inspect.md in hilen. The inspect
    # server announces only in a build that carries it, a shipped app has only
    # the types of its [local_network] table.
    lib = tvos.lib(tvos.SIMULATOR, app.lib_name)
    local_network.write_plist(plist, app.local_network, inspect=inspect.has_server(lib))

    os.chdir("mobile/tvOS")
    # An explicit destination fails with a clear "tvOS is not installed" message
    # when the platform is missing.
    run(
        f'xcodebuild -scheme {app.project_name} -destination "generic/platform=tvOS Simulator" '
        "-derivedDataPath build build"
    )
    return 0


if __name__ == "__main__":
    run_main(main)
