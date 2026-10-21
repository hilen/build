#!/usr/bin/env -S uv run -q --no-dev

# The Rust libs of the tvOS build. tvOS is a tier 3 target with no prebuilt std,
# so std is built too. There is no universal lib, the device and the simulator
# are both arm64 and the project picks the lib by its sdk.

from shared.util import run_main

from shared import config, lib_build, tvos


def main() -> int:
    app = config.read()
    line = (
        f"TVOS_DEPLOYMENT_TARGET={app.tvos_minimum_version} cargo build -p {app.app_name} --lib "
        f"--release --target {tvos.DEVICE} --target {tvos.SIMULATOR} -Z build-std=std,panic_abort"
    )
    libs = [tvos.lib(target, app.lib_name) for target in (tvos.DEVICE, tvos.SIMULATOR)]
    lib_build.build(app, line, libs, tvos.lib(tvos.DEVICE, app.lib_name))
    return 0


if __name__ == "__main__":
    run_main(main)
