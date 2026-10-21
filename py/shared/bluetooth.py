# The `[bluetooth]` table of hilen.toml, for an app on the `bluetooth` feature of
# hilen. macOS shows `usage` when it asks the user for Bluetooth, and it ends an
# app bundle that uses Bluetooth with no such text. `hilen-mobile` writes the
# same table into the phone projects.

import msgspec

from shared import toml
from shared.util import bail
from shared.xml import escape


class _Table(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    usage: str


class _Toml(msgspec.Struct, frozen=True):
    bluetooth: _Table | None = None


# None for an app with no `[bluetooth]` table.
def usage_of(hilen_toml: str) -> str | None:
    table = toml.decode(hilen_toml, _Toml, "[bluetooth] table").bluetooth
    if table is None:
        return None
    if not table.usage.strip():
        bail(
            "usage of [bluetooth] in hilen.toml is empty, macOS shows it when it asks the user "
            "for Bluetooth"
        )
    return table.usage


# The line of a Mac `Info.plist` with the text, for inside its top `<dict>`.
def plist_lines(usage: str) -> str:
    return f"  <key>NSBluetoothAlwaysUsageDescription</key><string>{escape(usage)}</string>\n"
