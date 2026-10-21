#!/usr/bin/env -S uv run -q --no-dev

# The Rust lib of the iOS build, a universal staticlib made by cargo lipo.

from shared.util import run_main

from shared import config, lib_build


def main() -> int:
    app = config.read()
    lib = f"target/universal/release/{app.lib_name}"
    line = (
        "rustup target add aarch64-apple-ios x86_64-apple-ios && cargo install cargo-lipo && "
        f"cargo lipo -p {app.app_name} --release"
    )
    lib_build.build(app, line, [lib], lib)
    return 0


if __name__ == "__main__":
    run_main(main)
