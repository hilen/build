# The `[camera]` table of hilen.toml. `usage` is the text iOS and a packaged Mac
# app show when the app asks for the camera, the builds write it into the app.
# An Android app gets the camera permission in its manifest. With no table the
# app never asks, see `camera` in hilen. The table holds 1 line, like
# `usage = "Takes photos of the object on the turntable."`.

from collections.abc import Sequence
from typing import Final

import msgspec

from shared import toml
from shared.util import bail
from shared.xml import escape

# The key of the text in an `Info.plist`.
USAGE_KEY: Final = "NSCameraUsageDescription"
# What a Mac app signed with the hardened runtime needs for the camera.
ENTITLEMENT: Final = "com.apple.security.device.camera"
# What an Android manifest needs for the camera.
ANDROID_PERMISSION: Final = "android.permission.CAMERA"


class _Table(msgspec.Struct, frozen=True):
    usage: str


class _Toml(msgspec.Struct, frozen=True):
    camera: _Table | None = None


# None for an app with no `[camera]` table.
def usage_of(hilen_toml: str) -> str | None:
    table = toml.decode(hilen_toml, _Toml, "[camera] table").camera
    if table is None:
        return None
    usage = table.usage.strip()
    if not usage:
        bail("usage of [camera] in hilen.toml is empty, the system shows it to the user")
    return usage


# The line of a Mac `Info.plist` with the text, for inside its top `<dict>`.
def plist_lines(usage: str) -> str:
    return f"  <key>{USAGE_KEY}</key><string>{escape(usage)}</string>\n"


# The entitlements file of a Mac app, each key turned on.
def entitlements(keys: Sequence[str]) -> str:
    lines = "".join(f"  <key>{key}</key><true/>\n" for key in keys)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
{lines}</dict>
</plist>
"""
