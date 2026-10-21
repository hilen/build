# The `[biometric]` table of hilen.toml, for an app on the `biometric` feature of
# hilen. `usage` is the text an iPhone or an iPad shows when the app asks for Face
# ID, the iOS build writes it into the app. Touch ID and a Mac need no text. The
# table holds 1 line, like `usage = "Face ID confirms each payment you send."`.

from typing import Final

import msgspec

from shared import toml
from shared.util import bail

# The key of the text in an `Info.plist`.
USAGE_KEY: Final = "NSFaceIDUsageDescription"


class _Table(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    usage: str


class _Toml(msgspec.Struct, frozen=True):
    biometric: _Table | None = None


# None for an app with no `[biometric]` table.
def usage_of(hilen_toml: str) -> str | None:
    table = toml.decode(hilen_toml, _Toml, "[biometric] table").biometric
    if table is None:
        return None
    usage = table.usage.strip()
    if not usage:
        bail(
            "usage of [biometric] in hilen.toml is empty, iOS shows it when it asks the user "
            "for Face ID"
        )
    return usage
