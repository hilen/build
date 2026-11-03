# The file types of the `[open_files]` table of hilen.toml, which the Mac
# packaging registers with the system. The app then shows in Open With for such
# a file, and the engine gives the path to the app, see `system::OpenFiles` in
# hilen. The rank Alternate keeps the default app of the user as it is.
#
# A type is an Apple uniform type like `public.movie`.

import msgspec

from shared import toml


class _OpenFiles(msgspec.Struct, frozen=True):
    types: tuple[str, ...] = ()


class _Toml(msgspec.Struct, frozen=True):
    open_files: _OpenFiles | None = None


def types_of(hilen_toml: str) -> tuple[str, ...]:
    found = toml.decode(hilen_toml, _Toml, "[open_files] table")
    return () if found.open_files is None else found.open_files.types


# The lines of a Mac `Info.plist` for inside its top `<dict>`.
def plist_lines(types: tuple[str, ...], name: str) -> str:
    items = "".join(f"<string>{kind}</string>" for kind in types)
    return (
        "  <key>CFBundleDocumentTypes</key>\n  <array>\n    <dict>\n"
        f"      <key>CFBundleTypeName</key><string>{name} file</string>\n"
        "      <key>CFBundleTypeRole</key><string>Editor</string>\n"
        "      <key>LSHandlerRank</key><string>Alternate</string>\n"
        f"      <key>LSItemContentTypes</key><array>{items}</array>\n"
        "    </dict>\n  </array>\n"
    )
