#!/usr/bin/env -S uv run -q --no-dev

# Builds an app for an LG webOS TV. The TV runs the app as a web page in a
# Chromium that never updates, 79 on a 2021 set, so the wasm is built for that
# browser and the start script trunk writes is rewritten for it. Then the app is
# packed. A hosted app is a small .ipk whose page sends the TV to the address the
# app is served from. A packaged app holds the whole dist and starts from the TV.
# `--dist` stops after the dist. `--dev` builds a dev package with the inspector
# of hilen, see "An installed TV app" in docs/inspect.md of hilen. It must never
# ship.
#
#   uv run ./build/web/webos.py [--dist] [--dev]

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import msgspec
from shared.run import probe, run
from shared.util import bail, run_main

from shared import webos

if TYPE_CHECKING:
    from shared.webos import Webos

# Chromium 79 knows only part of the wasm features a default Rust build turns on.
# It has no multivalue, no reference types and no BigInt at the JS border, so the
# build drops to the mvp cpu and turns these 4 back on.
_TARGET_FLAGS: Final = (
    "-Ctarget-cpu=mvp -Ctarget-feature=+mutable-globals,+sign-ext,+nontrapping-fptoint,+bulk-memory"
)
# The inspector answers on a worker thread, which needs shared memory. The flags
# of `drive.ts`, rustc adds none of them itself. The LG C1 has
# `SharedArrayBuffer` with no isolation headers.
_THREAD_FLAGS: Final = (
    "-Ctarget-feature=+atomics -Clink-arg=--shared-memory -Clink-arg=--import-memory "
    "-Clink-arg=--max-memory=2147483648 -Clink-arg=--export=__wasm_init_tls "
    "-Clink-arg=--export=__tls_size -Clink-arg=--export=__tls_align "
    "-Clink-arg=--export=__tls_base -Clink-arg=--export=__heap_base "
    "-Clink-arg=--export=__data_end"
)
_RGB_HEX: Final = 6
_RGBA_HEX: Final = 8
# What a dev package dials at its start. `hilen-inspect web-bridge --tunnel`
# carries this port of the TV to the Mac, the TV can't open a connection to the
# Mac itself. The same port as `PAGE_PORT` of hilen.
_INSPECT_URL: Final = "ws://127.0.0.1:7436/hilen-inspect"
# Chromium 79 of webOS lists WEBGL_compressed_texture_astc, but its object has no
# getSupportedProfiles, which came later. wgpu calls it to choose the ASTC
# features and the throw stops the app. An extension without the call is LDR
# only. It runs before the app script, so it is the first in head.
_ASTC_PROFILES: Final = """<script>
(function () {
    var getExtension = WebGL2RenderingContext.prototype.getExtension;
    WebGL2RenderingContext.prototype.getExtension = function (name) {
        var extension = getExtension.call(this, name);
        if (name === "WEBGL_compressed_texture_astc" && extension && \
!extension.getSupportedProfiles) {
            extension.getSupportedProfiles = function () {
                return ["ldr"];
            };
        }
        return extension;
    };
})();
</script>"""
# The page trunk builds a packaged app from, made next to index.html for the build
# and removed after it.
_PACKAGED_PAGE: Final = "webos.index.html"
_LINK: Final = 'data-trunk rel="rust"'


class _AppInfo(msgspec.Struct, frozen=True, omit_defaults=True):
    id: str
    version: str
    vendor: str
    type: str
    main: str
    title: str
    icon: str
    large_icon: str = msgspec.field(name="largeIcon")
    # The Back key reaches the page as key code 461 instead of moving the browser
    # history, the engine hands it on as Escape.
    disable_back_history_api: bool = msgspec.field(name="disableBackHistoryAPI")
    # The app calls no Luna API of the TV. The packer asks for the list also when
    # it is empty.
    required_acg: tuple[str, ...] = msgspec.field(name="requiredACG")
    # The V8 of an LG C1 compiles wasm with its slow optimizing compiler only,
    # Liftoff is off. With it the 6 MB wasm of flixen started Rust after 10 s in
    # place of 17.7 s. Lazy compilation and more compile tasks were measured too
    # and gave nothing on top. The TV reads this key only at install, an edit of
    # the installed file does nothing.
    v8_extra_flags: str = msgspec.field(name="v8ExtraFlags")
    # The TV shows it from the launch until the first frame, the compile of the
    # wasm is black otherwise.
    splash_background: str = msgspec.field(name="splashBackground")
    # The launcher tile is taller than the icon and fills the rest with black when
    # this is missing, a square icon got black bars at the top and the bottom on
    # an LG C1.
    icon_color: str | None = msgspec.field(name="iconColor", default=None)


# A packaged app opens from a file, where Chromium 79 loads no module script.
# Trunk builds it from a copy of index.html that asks wasm-bindgen for a classic
# script, which keeps the bindings in a global `wasm_bindgen`.
def _packaged_page(app: Webos) -> str:
    page = Path(app.crate_dir, "index.html").read_text(encoding="utf-8")
    if page.count(_LINK) != 1:
        bail(f"index.html of {app.crate_dir} needs exactly 1 <link {_LINK}>")
    classic = page.replace(_LINK, f'{_LINK} data-bindgen-target="no-modules"')
    Path(app.crate_dir, _PACKAGED_PAGE).write_text(classic, encoding="utf-8")
    return _PACKAGED_PAGE


def _build_dist(app: Webos, *, dev: bool):
    run("rustup target add wasm32-unknown-unknown")
    run("rustup component add rust-src")
    run("command -v trunk >/dev/null || cargo install --locked trunk")
    # RUSTFLAGS in the environment replaces the rustflags of the cargo config, so a
    # cfg the project sets there has to be said again.
    try:
        cargo_config = Path(".cargo/config.toml").read_text(encoding="utf-8")
    except OSError:
        cargo_config = ""
    tokio = "--cfg tokio_unstable " if "tokio_unstable" in cargo_config else ""
    default_features = "" if app.default_features else " --no-default-features"
    # A packaged app opens from a file:// address, where links that start at `/`
    # point at the root of the TV file system.
    public_url = " --public-url ./" if app.packaged else ""
    page = _packaged_page(app) if app.packaged else "index.html"
    # The standard library is built again with the same flags. `--no-sri` leaves
    # the integrity attributes out, the start script changes after the build and
    # its hash would no longer hold. `deploy-wasm` is the shipping profile with
    # fat LTO. Without Liftoff the TV compiles wasm with its slow optimizing
    # compiler only, about 4.7 s a MB on an LG C1, and with it the time still grows
    # with the code, so the TV build alone is built for size. Measured there in
    # flixen: opt-level 3 started Rust after 37.4 s, "s" after 24.6 s, "z" after
    # 20.2 s, at the same frame times.
    threads, inspect_url, inspect = "", "", ""
    if dev:
        print(f"a dev package: the inspector dials {_INSPECT_URL}")
        threads, inspect_url, inspect = (
            f" {_THREAD_FLAGS}",
            f"HILEN_INSPECT_URL={_INSPECT_URL} ",
            ",hilen/inspect",
        )
    try:
        run(
            f'cd "{app.crate_dir}" && RUSTFLAGS="{tokio}{_TARGET_FLAGS}{threads}" '
            "CARGO_UNSTABLE_BUILD_STD=std,panic_abort "
            f"CARGO_PROFILE_DEPLOY_WASM_OPT_LEVEL=z {inspect_url}"
            f"trunk build {page} --release --cargo-profile deploy-wasm --no-sri{public_url} "
            f"--features {app.features}{inspect}{default_features}"
        )
    finally:
        if app.packaged:
            Path(app.crate_dir, _PACKAGED_PAGE).unlink(missing_ok=True)


def _fix_start_script(app: Webos):
    path = Path(app.crate_dir, "dist/index.html")
    try:
        page = path.read_text(encoding="utf-8")
    except OSError:
        bail(f"no {path} after the build")
    if app.packaged:
        js, wasm = webos.packaged_files(page)
        code = Path(app.crate_dir, "dist", js).read_text(encoding="utf-8")
        if "import.meta" in code or any(line.startswith("export ") for line in code.splitlines()):
            bail(f"{js} is still an ES module, the no-modules target of wasm-bindgen did not apply")
        fixed = webos.classic_start_script(page, js, wasm)
    else:
        fixed = webos.without_top_level_await(page)
    if "await init(" in fixed:
        bail(f"the start script of {path} still has a top level await")
    if fixed.count("<head>") != 1:
        bail(f"{path} needs exactly 1 <head> for the ASTC script")
    path.write_text(fixed.replace("<head>", f"<head>\n{_ASTC_PROFILES}"), encoding="utf-8")
    print(f"start script of {path} rewritten for Chromium 79")


def _has(tool: str) -> bool:
    return bool(probe(f"command -v {tool}").strip())


# A square copy of the icon with this side, with the tool the system has.
def _icon(source: str, target: str, side: int):
    if _has("sips"):
        shutil.copyfile(source, target)
        run(f'sips -z {side} {side} "{target}" >/dev/null')
    elif _has("magick"):
        run(f'magick "{source}" -resize {side}x{side} "{target}"')
    else:
        bail("no sips and no magick to scale the icon, install ImageMagick")


# The color of the top left pixel of the icon, the background of the tile around
# it. None when that pixel is transparent.
def _icon_color(source: str) -> str | None:
    if _has("sips"):
        bmp = Path("target/webos/icon-color.bmp")
        run(f'sips -s format bmp "{source}" --out {bmp} >/dev/null')
        data = bmp.read_bytes()
        bmp.unlink()
        pixel = webos.bmp_top_left(data)
        return None if pixel is None else "#{:02x}{:02x}{:02x}".format(*pixel)
    if _has("magick"):
        pixel = probe(f"magick \"{source}\" -format '%[hex:p{{0,0}}]' info:").strip()
        if len(pixel) < _RGB_HEX:
            bail(f"magick gave no pixel for {source}: {pixel}")
        transparent = len(pixel) == _RGBA_HEX and pixel.endswith("00")
        return None if transparent else f"#{pixel[:_RGB_HEX].lower()}"
    bail("no sips and no magick to read the icon color, install ImageMagick")
    return None


# The icon in the middle of a screen of the TV, 1920 by 1080, filled with the
# background color of the icon so its edge does not show.
def _splash(source: str, target: str, color: str):
    if _has("sips"):
        shutil.copyfile(source, target)
        pad = color.lstrip("#")
        run(
            f'sips -z 320 320 "{target}" >/dev/null && '
            f'sips --padToHeightWidth 1080 1920 --padColor {pad} "{target}" >/dev/null'
        )
    elif _has("magick"):
        run(
            f'magick -size 1920x1080 "xc:{color}" \\( "{source}" -resize 320x320 \\) '
            f'-gravity center -composite "{target}"'
        )
    else:
        bail("no sips and no magick to make the splash, install ImageMagick")


def _pack(app: Webos):
    url = None if app.packaged else app.url
    if not app.packaged and url is None:
        bail(
            "hilen.toml has no url in its [webos] table, the hosted app needs the address it loads"
        )
    if not Path(app.icon).exists():
        bail(f"no icon at {app.icon}, set icon in the [webos] table of hilen.toml")
    folder = Path(f"target/webos/{app.name}")
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    _icon(app.icon, f"{folder}/icon.png", 80)
    _icon(app.icon, f"{folder}/largeIcon.png", 130)
    color = _icon_color(app.icon)
    _splash(app.icon, f"{folder}/splash.png", color or "#ffffff")
    info = _AppInfo(
        id=app.id,
        version=app.version,
        vendor=app.title,
        type="web",
        main="index.html",
        title=app.title,
        icon="icon.png",
        large_icon="largeIcon.png",
        disable_back_history_api=True,
        required_acg=(),
        v8_extra_flags="--liftoff",
        splash_background="splash.png",
        icon_color=color,
    )
    (folder / "appinfo.json").write_bytes(msgspec.json.format(msgspec.json.encode(info), indent=2))
    if url is None:
        run(f'cp -R "{app.crate_dir}/dist/." "{folder}/"')
    else:
        (folder / "index.html").write_text(webos.launcher_page(app.title, url), encoding="utf-8")
    # The folder is whole before this check, so a machine with the packer can pack
    # the folder of a builder that has none.
    if not _has("ares-package"):
        bail(
            "ares-package is not installed, run: npm install -g @webos-tools/cli. "
            f"The folder to pack is {folder}"
        )
    Path("dist").mkdir(exist_ok=True)
    # The minifier of the tool chokes on new JavaScript, and trunk already
    # minified the dist of a packaged app.
    run(f'ares-package --no-minify "{folder}" -o dist')
    start = "it holds the whole app" if url is None else f"it loads {url}"
    ipk = f"dist/{app.id}_{app.version}_all.ipk"
    print(f"packed {ipk}, {start}. Install it with: ares-install {ipk}")


def main() -> int:
    app = webos.read()
    dist_only = "--dist" in sys.argv[1:]
    dev = "--dev" in sys.argv[1:]
    if dev and "HILEN_RELEASE" in os.environ:
        bail("a dev package carries the inspector and never ships, HILEN_RELEASE is set")
    _build_dist(app, dev=dev)
    _fix_start_script(app)
    if dist_only:
        print(f"the dist for the TV is in {app.crate_dir}/dist")
        return 0
    _pack(app)
    return 0


if __name__ == "__main__":
    run_main(main)
