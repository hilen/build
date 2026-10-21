#!/usr/bin/env -S uv run -q --no-dev

# Builds the static ffmpeg libraries hilen links for video playback, see
# docs/video.md in hilen. Run once per target. With no argument it builds for the
# host. On a Mac `aarch64-apple-ios` cross builds for an iPhone,
# `x86_64-apple-ios` for the simulator and `aarch64-apple-ios-sim` for the
# simulator of an Apple Silicon Mac, `aarch64-apple-tvos` for an Apple TV and
# `aarch64-apple-tvos-sim` for its simulator. The archive in dist/ goes to a
# release of this repo and the forked ffmpeg-sys-next downloads it from there, so
# a normal build never compiles ffmpeg. The configure flags mirror what the
# ffmpeg-sys-next `build` feature passes, minus debug info, so a locally built
# archive and a downloaded one link the same way.

import hashlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from shared.run import capture, run
from shared.util import ScriptError, bail, run_main

_VERSION: Final = "9.0"
# The software AV1 decoder, built here and packed into the archive. ffmpeg has no
# AV1 decoder of its own that runs without a hardware one.
_DAV1D: Final = "1.5.4"
# The oldest iOS the engine runs on, see docs/ios.md in hilen.
_IOS_MINIMUM: Final = "12.0"
# The oldest tvOS, the default of `tvos_minimum_version` in hilen.toml.
_TVOS_MINIMUM: Final = "15.0"

_FLAGS: Final = (
    "--enable-static",
    "--disable-shared",
    "--enable-pic",
    "--disable-autodetect",
    "--disable-programs",
    "--disable-doc",
    "--disable-debug",
    "--enable-stripping",
    "--enable-pthreads",
    "--enable-avcodec",
    "--enable-avformat",
    "--enable-swresample",
    "--enable-swscale",
    "--disable-avdevice",
    # Only the filters the engine uses: atempo changes the speed of the sound and
    # keeps its pitch, the other 2 are the ends of its graph.
    "--enable-avfilter",
    "--disable-filters",
    "--enable-filter=atempo",
    "--enable-filter=abuffer",
    "--enable-filter=abuffersink",
    # zlib for files with compressed headers, dav1d for AV1 where the hardware has
    # no decoder.
    "--enable-zlib",
    "--enable-libdav1d",
    "--pkg-config-flags=--static",
    "--disable-gpl",
    "--disable-version3",
    "--disable-nonfree",
)


# What a cross build for an Apple device needs to know.
@dataclass(frozen=True, slots=True)
class Cross:
    # The name ffmpeg and clang have for the processor.
    arch: str
    # The name meson has for it.
    cpu_family: str
    sdk: str
    # The name meson has for the system of the device.
    subsystem: str
    version_min: str
    # The simulator slice has no assembly. It only runs the UI tests under
    # Rosetta, and the x86 assembly would need nasm on the build machine.
    assembly: bool


_CROSS: Final = {
    "aarch64-apple-ios": Cross(
        "arm64",
        "aarch64",
        "iphoneos",
        "ios",
        f"-miphoneos-version-min={_IOS_MINIMUM}",
        assembly=True,
    ),
    "x86_64-apple-ios": Cross(
        "x86_64",
        "x86_64",
        "iphonesimulator",
        "ios-simulator",
        f"-mios-simulator-version-min={_IOS_MINIMUM}",
        assembly=False,
    ),
    # The simulator of an Apple Silicon Mac, for a hot build, see
    # docs/hot-reload.md in hilen. No arm64 simulator is older than iOS 14.
    "aarch64-apple-ios-sim": Cross(
        "arm64",
        "aarch64",
        "iphonesimulator",
        "ios-simulator",
        "-mios-simulator-version-min=14.0",
        assembly=True,
    ),
    "aarch64-apple-tvos": Cross(
        "arm64",
        "aarch64",
        "appletvos",
        "tvos",
        f"-mtvos-version-min={_TVOS_MINIMUM}",
        assembly=True,
    ),
    "aarch64-apple-tvos-sim": Cross(
        "arm64",
        "aarch64",
        "appletvsimulator",
        "tvos-simulator",
        f"-mtvos-simulator-version-min={_TVOS_MINIMUM}",
        assembly=True,
    ),
}


def cross_for(triple: str) -> Cross:
    cross = _CROSS.get(triple)
    if cross is None:
        bail(f"no cross build for {triple}, only {', '.join(_CROSS)}")
    return cross


# The compiler and the machine of the device, for the meson build of dav1d.
def meson_cross_file(cross: Cross, sdk_path: str) -> str:
    return f"""[binaries]
c = ['clang', '-arch', '{cross.arch}', '-isysroot', '{sdk_path}']
ar = 'ar'
strip = 'strip'

[built-in options]
c_args = ['{cross.version_min}']
c_link_args = ['{cross.version_min}']

[host_machine]
system = 'darwin'
subsystem = '{cross.subsystem}'
cpu_family = '{cross.cpu_family}'
cpu = '{cross.arch}'
endian = 'little'
"""


def _host_triple() -> str:
    for line in capture("rustc -vV").splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ").strip()
    bail("rustc -vV printed no host line")
    return None


def _jobs() -> str:
    try:
        return capture("sysctl -n hw.ncpu" if sys.platform == "darwin" else "nproc")
    except ScriptError:
        return "4"


# Autodetect is off, so the system TLS is named here too. Without it the archive
# has no https protocol.
def _hardware(cross: Cross | None) -> str:
    if cross is not None or sys.platform == "darwin":
        return "--enable-videotoolbox --enable-securetransport"
    if sys.platform == "linux":
        return "--enable-vaapi"
    if sys.platform == "win32":
        return "--enable-d3d11va"
    bail("no hardware decoder flag for this host")
    return None


# dav1d goes first, into the same prefix, so ffmpeg finds it through pkg-config
# and its static library lands next to the ffmpeg ones.
def _build_dav1d(
    root: Path, triple: str, dist: Path, build: Path, cross_files: tuple[Cross, str] | None
):
    src = root / "target/dav1d-src"
    out = root / f"target/dav1d-build-{triple}"
    if not (src / "meson.build").exists():
        run(f"git clone --depth=1 -b {_DAV1D} https://code.videolan.org/videolan/dav1d.git {src}")
    shutil.rmtree(out, ignore_errors=True)
    extra = ""
    if cross_files is not None:
        cross, sdk_path = cross_files
        file = build / "dav1d-cross.meson"
        file.write_text(meson_cross_file(cross, sdk_path), encoding="utf-8")
        extra = f" --cross-file={file}" + ("" if cross.assembly else " -Denable_asm=false")
    run(
        f"meson setup {out} {src} --prefix={dist} --libdir=lib --default-library=static "
        f"--buildtype=release -Denable_tools=false -Denable_tests=false{extra}"
    )
    run(f"ninja -C {out} install")


def _cross_flags(cross: Cross | None, sdk_path: str) -> str:
    if cross is None:
        return ""
    target = f"-arch {cross.arch} {cross.version_min}"
    assembly = "" if cross.assembly else " --disable-x86asm"
    # A cross build looks for a pkg-config with the prefix of the tools, so the
    # plain one is named.
    return (
        f" --enable-cross-compile --target-os=darwin --arch={cross.arch} "
        f"--cc='xcrun --sdk {cross.sdk} clang' --sysroot={sdk_path} --extra-cflags='{target}' "
        f"--extra-ldflags='{target}' --pkg-config=pkg-config{assembly}"
    )


def main() -> int:
    host = _host_triple()
    triple = sys.argv[1] if len(sys.argv) > 1 else host
    cross = None if triple == host else cross_for(triple)
    root = Path.cwd()
    src = root / "target/ffmpeg-src"
    # The host build keeps its old place, docs/video.md names it.
    dist = root / (f"target/ffmpeg-dist-{triple}" if cross is not None else "target/ffmpeg-dist")
    build = root / f"target/ffmpeg-build-{triple}"
    if not (src / "configure").exists():
        run(f"git clone --depth=1 -b release/{_VERSION} https://github.com/FFmpeg/FFmpeg {src}")
    # Every target builds in a folder of its own. ffmpeg refuses that while the
    # source folder holds a build from before this script did so.
    if (src / "config.h").exists():
        run(f"make -C {src} distclean")
    shutil.rmtree(dist, ignore_errors=True)
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True)
    sdk_path = "" if cross is None else capture(f"xcrun --sdk {cross.sdk} --show-sdk-path")
    _build_dav1d(root, triple, dist, build, None if cross is None else (cross, sdk_path))

    # LIBDIR, not PATH, on a cross build: a library of the host must never answer
    # for the device.
    pkg_config = "PKG_CONFIG_PATH" if cross is None else "PKG_CONFIG_LIBDIR"
    run(
        f"cd {build} && {pkg_config}={dist}/lib/pkgconfig {src}/configure --prefix={dist} "
        f"{' '.join(_FLAGS)} {_hardware(cross)}{_cross_flags(cross, sdk_path)}"
    )
    run(f"make -C {build} -j{_jobs()} install")

    # What the archive needs linked besides the ffmpeg libraries, 1
    # `<kind>=<name>` per line. The forked ffmpeg-sys-next reads it.
    (dist / "lib/link.txt").write_text("static=dav1d\ndylib=z\n", encoding="utf-8")
    Path("dist").mkdir(exist_ok=True)
    name = f"ffmpeg-{_VERSION}-{triple}"
    archive = f"dist/{name}.tar.gz"
    run(f"tar -C {dist} --exclude=lib/pkgconfig -czf {archive} include lib")
    sha = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    Path(f"dist/{name}.sha256").write_text(f"{sha}  {name}.tar.gz\n", encoding="utf-8")
    print(archive)
    print(sha)
    return 0


if __name__ == "__main__":
    run_main(main)
