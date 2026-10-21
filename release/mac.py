#!/usr/bin/env -S uv run -q --no-dev

# The mac release: the binary, the .app bundle, Developer ID signing,
# notarization and the dmg. The binary is universal unless `mac_targets` in the
# [release] table of hilen.toml names 1 target, <arch> is then `arm64` or `x64`.
# A local run without the Apple secrets still makes an unsigned dmg to test the
# bundle with, but in CI a missing APPLE_SIGNING_IDENTITY fails the build, so an
# unsigned release can never ship silently. Outputs in dist/:
#   <name>-<v>-mac-<arch>.dmg      first install
#   <name>-<v>-macos-<arch>        the bare binary the updater swaps in
#   <daemon>-<v>-macos-<arch>      each daemon of `daemons`, bare and signed

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

from shared.run import capture, run, run_secret
from shared.util import ScriptError, bail, run_main

from shared import bluetooth, camera, inspect, links, release

if TYPE_CHECKING:
    from shared.release import Release

_NOTARIZE_LIMIT_SECS: Final = 900
_KEYCHAIN: Final = "~/Library/Keychains/ci-signing.keychain-db"
_KIB: Final = 1024


def _unlock_keychain():
    # The password stays a shell variable, so it is never part of a printed
    # command.
    if "APPLE_CI_KEYCHAIN_PASSWORD" not in os.environ:
        bail("APPLE_CI_KEYCHAIN_PASSWORD is not set")
    run_secret(f'security unlock-keychain -p "$APPLE_CI_KEYCHAIN_PASSWORD" {_KEYCHAIN}')
    run_secret(
        "security set-key-partition-list -S apple-tool:,apple: -k "
        f'"$APPLE_CI_KEYCHAIN_PASSWORD" {_KEYCHAIN} > /dev/null'
    )
    run(f"security list-keychains -d user -s {_KEYCHAIN} ~/Library/Keychains/login.keychain-db")


def _info_plist(r: Release) -> str:
    extra = (
        ("" if r.link_scheme is None else links.plist_lines(r.link_scheme, r.bundle_id))
        + ("" if r.camera_usage is None else camera.plist_lines(r.camera_usage))
        + ("" if r.bluetooth_usage is None else bluetooth.plist_lines(r.bluetooth_usage))
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{r.name}</string>
  <key>CFBundleDisplayName</key><string>{r.name}</string>
  <key>CFBundleIdentifier</key><string>{r.bundle_id}</string>
  <key>CFBundleExecutable</key><string>{r.name}</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{r.version}</string>
  <key>CFBundleVersion</key><string>{r.version}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>NSHighResolutionCapable</key><true/>
{extra}</dict>
</plist>
"""


def _bundle(r: Release, universal: str) -> str:
    app = f"target/release/bundle/{r.name}.app"
    contents = Path(app) / "Contents"
    shutil.rmtree(app, ignore_errors=True)
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir(parents=True)
    shutil.copyfile(universal, contents / "MacOS" / r.name)
    try:
        shutil.copyfile("assets/icon.icns", contents / "Resources" / "icon.icns")
    except OSError as err:
        bail(f"assets/icon.icns: {err}")
    (contents / "Info.plist").write_text(_info_plist(r), encoding="utf-8")
    return app


def _notarize(file: str):
    for var in ("APPLE_ID_EMAIL", "APPLE_APP_SPECIFIC_PASSWORD", "APPLE_TEAM_ID"):
        if var not in os.environ:
            bail(f"{var} is not set")
    # The secrets stay shell variables and the command is not echoed, the
    # release logs once showed the password. notarytool has no limit on the
    # upload, a stalled one hung a release for 28 minutes, so the alarm of perl
    # kills it. A normal upload and wait takes under 5 minutes.
    print(f"notarizing {file}", flush=True)
    try:
        run_secret(
            f"perl -e 'alarm shift; exec @ARGV' {_NOTARIZE_LIMIT_SECS} xcrun notarytool submit "
            f'"{file}" --apple-id "$APPLE_ID_EMAIL" --password "$APPLE_APP_SPECIFIC_PASSWORD" '
            '--team-id "$APPLE_TEAM_ID" --wait'
        )
    except ScriptError as err:
        bail(f"notarizing {file} failed or took over {_NOTARIZE_LIMIT_SECS} seconds: {err}")
    if file.endswith(".dmg"):
        run(f'xcrun stapler staple "{file}"')


# The app is notarized on its own before it goes into the dmg, so the bundle
# carries a stapled ticket and starts offline after a drag install.
def _notarize_app(app: str):
    zip_path = f"{app}.zip"
    run(f'ditto -c -k --keepParent "{app}" "{zip_path}"')
    _notarize(zip_path)
    run(f'xcrun stapler staple "{app}"')
    Path(zip_path).unlink()


def _make_dmg(r: Release, app: str, dmg: str):
    staging = "target/release/bundle/dmg"
    shutil.rmtree(staging, ignore_errors=True)
    Path(staging).mkdir(parents=True)
    run(f'cp -R "{app}" {staging}/')
    run(f"ln -s /Applications {staging}/Applications")
    Path(dmg).unlink(missing_ok=True)
    # Left to itself hdiutil sizes the image from the folder, and now and then its
    # guess is too small: `create failed - No space left on device`, on a disk with
    # 431 GB free, at blackforge v0.2.6. So the size is given, the folder plus a
    # third. The UDZO format packs the free space away.
    used = capture(f"du -sk {staging}")
    try:
        kb = int(used.split()[0])
    except ValueError, IndexError:
        bail(f"du gave no size for {staging}: {used}")
    mb = kb // _KIB * 4 // 3 + 32
    run(
        f'hdiutil create -size {mb}m -volname "{r.name}" -srcfolder {staging} -ov -format UDZO '
        f'"{dmg}"'
    )


def _lipo(r: Release, binary: str, arch: str, name: str) -> str:
    universal = f"target/release/{name}-{arch}"
    slices = " ".join(f"target/{target}/release/{binary}" for target in r.mac_targets)
    run(f"lipo -create -output {universal} {slices}")
    inspect.refuse(universal)
    return universal


# A daemon is only the bare binary, signed with the identity so Gatekeeper lets
# it run, no bundle, no dmg and no notarization.
def _daemons(r: Release, arch: str, signing: str | None):
    for daemon in r.daemons:
        for target in r.mac_targets:
            run(
                f"cargo build --locked --release -p {daemon.name} --bin {daemon.bin} "
                f"--target {target}"
            )
        universal = _lipo(r, daemon.bin, arch, daemon.name)
        if signing is not None:
            run(f'codesign --force --options runtime --timestamp --sign "{signing}" "{universal}"')
        bare = f"dist/{daemon.artifact(f'macos-{arch}')}"
        shutil.copyfile(universal, bare)
        r.sign([bare])
        print(f"built {bare}")


def main() -> int:
    inspect.mark_release()
    r = release.read()
    arch = r.mac_arch()
    Path("dist").mkdir(exist_ok=True)
    # lipo writes here, and a fresh checkout that only built with --target has no
    # such folder yet.
    Path("target/release").mkdir(parents=True, exist_ok=True)
    signing = os.environ.get("APPLE_SIGNING_IDENTITY") or None
    if signing is None and "CI" in os.environ:
        bail("APPLE_SIGNING_IDENTITY is not set, refusing to build an unsigned release in CI")
    if signing is not None:
        _unlock_keychain()

    # The runner shell starts without the interactive env, so cc has no sysroot
    # without this and native C deps fail to compile.
    os.environ["SDKROOT"] = capture("xcrun --sdk macosx --show-sdk-path")
    for target in r.mac_targets:
        run(f"rustup target add {target}")
        run(f"cargo build --locked --release -p {r.name} --bin {r.bin} --target {target}")
    universal = _lipo(r, r.bin, arch, r.name)

    app = _bundle(r, universal)
    # The hardened runtime keeps the camera closed to an app without the
    # entitlement. The bare binary gets it too, the updater puts it into the
    # bundle.
    entitlements = ""
    if r.camera_usage is not None:
        path = f"target/release/bundle/{r.name}.entitlements"
        Path(path).write_text(camera.entitlements(), encoding="utf-8")
        entitlements = f' --entitlements "{path}"'
    if signing is not None:
        for target in (
            f'--deep --options runtime --timestamp{entitlements} --sign "{signing}" "{app}"',
            f'--options runtime --timestamp{entitlements} --sign "{signing}" "{universal}"',
        ):
            run(f"codesign --force {target}")
        _notarize_app(app)

    dmg = f"dist/{r.artifact(f'mac-{arch}.dmg')}"
    _make_dmg(r, app, dmg)
    if signing is not None:
        _notarize(dmg)
    print(f"built {dmg}")

    bare = f"dist/{r.artifact(f'macos-{arch}')}"
    shutil.copyfile(universal, bare)
    r.sign([bare])
    print(f"built {bare}")
    _daemons(r, arch, signing)
    return 0


if __name__ == "__main__":
    run_main(main)
