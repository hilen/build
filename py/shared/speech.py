# The `[speech] usage` table of hilen.toml, for an app on the `speech` feature of
# hilen. iOS and a packaged Mac app show `usage` when the app asks for the
# microphone, and stop an app that asks with no text. The table holds 1 line,
# like `usage = "Turns what you say into the text of a prompt."`.

from typing import Final

import msgspec

from shared import toml
from shared.util import bail
from shared.xml import escape

# The key of the text in an `Info.plist`.
USAGE_KEY: Final = "NSMicrophoneUsageDescription"
# What a Mac app signed with the hardened runtime needs for the microphone.
ENTITLEMENT: Final = "com.apple.security.device.audio-input"


class _Table(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    usage: str


class _Toml(msgspec.Struct, frozen=True):
    speech: _Table | None = None


# None for an app with no `[speech]` table.
def usage_of(hilen_toml: str) -> str | None:
    table = toml.decode(hilen_toml, _Toml, "[speech] table").speech
    if table is None:
        return None
    usage = table.usage.strip()
    if not usage:
        bail("usage of [speech] in hilen.toml is empty, the system shows it to the user")
    return usage


# The line of a Mac `Info.plist` with the text, for inside its top `<dict>`.
def plist_lines(usage: str) -> str:
    return f"  <key>{USAGE_KEY}</key><string>{escape(usage)}</string>\n"
