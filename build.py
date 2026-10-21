#!/usr/bin/env -S uv run -q --no-dev

# The CI build of a hilen app: the desktop build and tests, `ios` for the iOS
# project, `android` for the APK in docker.

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from shared.run import probe, run
from shared.util import run_main

from shared import android, camera, config, inspect, toml

if TYPE_CHECKING:
    from shared.config import Config

# Gradle misses changed inputs on a docker bind mount even with vfs watching off
# and packs a stale .so into the APK. Removing the jni intermediates forces the
# merge, strip and package tasks every build.
_STALE_JNI: Final = (
    "mobile/android/app/build/intermediates/merged_jni_libs",
    "mobile/android/app/build/intermediates/merged_native_libs",
    "mobile/android/app/build/intermediates/stripped_native_libs",
)


def _fix_generated_project(app: Config):
    android.edit(android.GRADLE, android.fix_gradle)
    has_camera = camera.usage_of(toml.read_text()) is not None
    permission = camera.ANDROID_PERMISSION if has_camera else None
    android.edit(
        android.MANIFEST,
        lambda text: android.fix_manifest(
            text, camera_permission=permission, multicast=app.local_network is not None
        ),
    )
    # File watching can't work in the container.
    properties = Path(android.PROPERTIES)
    content = properties.read_text(encoding="utf-8")
    if "org.gradle.vfs.watch" not in content:
        properties.write_text(f"{content}\norg.gradle.vfs.watch=false\n", encoding="utf-8")


def _build_android(app: Config):
    run("rustup toolchain install")
    run(
        "rustup target add armv7-linux-androideabi aarch64-linux-android i686-linux-android "
        "x86_64-linux-android"
    )
    run("cargo install hilen-mobile --locked")
    run("hilen-mobile")
    _fix_generated_project(app)
    abi = os.environ.get("HILEN_ANDROID_ABI", "")
    if abi:
        android.edit(android.GRADLE, lambda text: android.limit_targets(text, abi))
    for folder in _STALE_JNI:
        shutil.rmtree(folder, ignore_errors=True)
    os.chdir("mobile/android")
    run("chmod +x ./gradlew")
    run("./gradlew assembleDebug" if abi else "./gradlew build")
    # A test build of demo carries the inspect server on purpose, only a shipped
    # build is checked. The .so of every ABI sits under this folder.
    if inspect.is_release():
        inspect.refuse("app/build/rustJniLibs/android")


# Amazon Linux is checked before Fedora on purpose. Its os-release carries
# ID_LIKE="fedora", so testing Fedora first sends it down the dnf branch and the
# yum packages it needs are never installed.
def _install_linux_deps(release: str, uname: str) -> int:
    if "amazon" in release:
        print("Amazon")
        run("sudo yum install -y gcc gcc-c++ alsa-lib-devel")
    elif "fedora" in release:
        print("Fedora")
        run(
            "sudo dnf install -y libXcursor-devel libXi-devel libXinerama-devel libXrandr-devel "
            "perl make cmake automake gcc gcc-c++ kernel-devel alsa-lib-devel-* dbus-devel "
            "pkgconf-pkg-config"
        )
    elif "freebsd" in uname:
        print("Freebsd")
        run("sudo pkg update")
        run("sudo pkg install cmake xorg pkgconf alsa-utils")
    elif Path("/etc/arch-release").exists():
        print("Arch")
        run("sudo pacman -S gcc pkg-config cmake openssl make alsa-lib alsa-utils --noconfirm")
    elif "ubuntu" in release or "debian" in release:
        print("Debian")
        deps = (
            "cmake mesa-common-dev libgl1-mesa-dev libglu1-mesa-dev xorg-dev libasound2-dev "
            "pkg-config libssl-dev libdbus-1-dev"
        )
        if platform.machine().lower() not in {"aarch64", "arm64"}:
            deps += " build-essential"
        run("sudo apt update")
        run(f"sudo apt -y install {deps}")
    elif "opensuse" in release:
        print("openSUSE")
        run("sudo zypper refresh")
        run("sudo zypper update")
        run("sudo zypper install -y --type pattern devel_basis")
        run("sudo zypper install -y --type pattern devel_C_C++")
        run("sudo zypper install -y alsa-lib llvm llvm-devel clang")
    else:
        print("Unknown distro")
        return 1
    return 0


def main() -> int:
    app = config.read()
    args = " ".join(sys.argv[1:]).lower()
    ios = "ios" in args
    with_android = "android" in args
    print(f"APP_NAME: {app.app_name}")
    print(f"PROJECT_NAME: {app.project_name}")

    # The android build always runs inside docker, locally and in CI, so the host
    # needs no Android tooling. The env var marks being inside already.
    if with_android and "HILEN_ANDROID_DOCKER_BUILD" not in os.environ:
        run("uv run -q --no-dev ./build/in_docker_android.py")
        return 0

    is_linux = sys.platform == "linux"
    unix = sys.platform == "darwin" or is_linux
    uname = probe("uname -a").lower() if unix else ""
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8").lower() if is_linux else ""
    except OSError:
        release = ""
    print(f"uname: {uname}")
    print(f"system: {sys.platform}")
    print(f"arch: {platform.machine()}")

    if with_android:
        _build_android(app)
        return 0
    if is_linux:
        print("Lin setup")
        if _install_linux_deps(release, uname) != 0:
            return 1
    if unix:
        print("Installing rustup:")
        run("curl https://sh.rustup.rs -sSf | sh -s -- -y")
        os.environ["PATH"] = f"{os.environ.get('HOME', '')}/.cargo/bin:{os.environ.get('PATH', '')}"
    if ios:
        run("uv run -q --no-dev ./build/ios/build-project.py")
    else:
        run("cargo build --all")
        run("cargo test --all")
    return 0


if __name__ == "__main__":
    run_main(main)
