#!/usr/bin/env -S uv run -q --no-dev

# Builds the Android APK of the app in docker, so the host needs no Android
# tooling.

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from shared.util import bail, run_main

from shared import config, inspect


def _docker(args: Sequence[str]):
    print(f"docker {' '.join(args)}", flush=True)
    if subprocess.run(["docker", *args], check=False).returncode != 0:
        bail(f"docker {' '.join(args)} failed")


def main() -> int:
    # Named after the app, so 2 hilen apps on 1 machine do not share an image or
    # fight over the caches of each other.
    image = f"{config.read().app_name}-android"
    # Named volumes keep the Rust toolchain, the cargo registry and the gradle
    # caches across runs, so only the first build downloads them. The volumes
    # seed themselves from the image content on first use, which is how the
    # rustup binary of the image survives the mount.
    volumes = (
        f"{image}-rustup:/usr/local/rustup",
        f"{image}-cargo:/usr/local/cargo",
        f"{image}-gradle:/root/.gradle",
        # Keeps the generated debug keystore, so the APK signature stays stable
        # and `adb install -r` works across builds.
        f"{image}-android-home:/root/.android",
    )
    _docker(["build", "--platform", "linux/amd64", "-t", image, "./build/android"])

    args = [
        "run",
        "--rm",
        "-t",
        "--platform",
        "linux/amd64",
        "--mount",
        f"type=bind,source={Path.cwd()},target=/host",
    ]
    for volume in volumes:
        args += ["-v", volume]
    args += [
        "-w",
        "/host",
        "-e",
        "HILEN_ANDROID_DOCKER_BUILD=true",
        # Release rustc under Rosetta eats gigabytes per job. Uncapped jobs OOM
        # the whole container on a default Docker Desktop VM, which dies silently
        # mid build with no error from cargo or gradle.
        "-e",
        "CARGO_BUILD_JOBS=4",
        # No host lane compiles the android code, this build is its only lint, so
        # a warning here fails it like clippy fails desktop.
        "-e",
        "RUSTFLAGS=-D warnings",
    ]
    abi = os.environ.get("HILEN_ANDROID_ABI", "")
    if abi:
        args += ["-e", f"HILEN_ANDROID_ABI={abi}"]
    # By name, so the container is a release build only when the host is.
    if inspect.is_release():
        args += ["-e", inspect.RELEASE_ENV]
    args += [image, "/bin/bash", "-c", "uv run -q --no-dev ./build/build.py android"]
    _docker(args)
    return 0


if __name__ == "__main__":
    run_main(main)
