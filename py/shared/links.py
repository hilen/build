# The url scheme of the `[links]` table of hilen.toml, which the desktop
# packaging registers with the system. A click on a link of the scheme, like
# `shopping://invite/x7k2`, then starts the app with the link, and the engine
# gives it to the app, see `system::Links` in hilen. The domains of the table
# are for the phones, `hilen-mobile` writes them.
#
# Not set, the scheme is project_name in lower case with `-` for `_`, the same
# rule as `link_scheme!` of the engine and as `hilen-mobile`.

import msgspec

from shared import toml
from shared.util import bail


class _Links(msgspec.Struct, frozen=True):
    scheme: str | None = None


class _Toml(msgspec.Struct, frozen=True):
    project_name: str | None = None
    links: _Links | None = None


def _valid(scheme: str) -> bool:
    if not scheme or not ("a" <= scheme[0] <= "z"):
        return False
    return all(("a" <= c <= "z") or ("0" <= c <= "9") or c in "+-." for c in scheme)


# None for an app with no `[links]` table.
def scheme_of(hilen_toml: str) -> str | None:
    found = toml.decode(hilen_toml, _Toml, "[links] table")
    if found.links is None:
        return None
    scheme = found.links.scheme
    if scheme is None:
        if found.project_name is None:
            bail("project_name not found in hilen.toml")
        scheme = found.project_name.lower().replace("_", "-")
    if not _valid(scheme):
        bail(
            f'the link scheme "{scheme}" in hilen.toml must start with a small letter and have '
            "only small letters, digits, +, - and ."
        )
    if scheme in {"http", "https", "file"}:
        bail(f'the link scheme "{scheme}" in hilen.toml belongs to the system')
    return scheme


# The lines of a Mac `Info.plist` that register the scheme, for inside its top
# `<dict>`.
def plist_lines(scheme: str, bundle_id: str) -> str:
    return (
        "  <key>CFBundleURLTypes</key>\n  <array>\n    <dict>\n"
        f"      <key>CFBundleURLName</key><string>{bundle_id}</string>\n"
        f"      <key>CFBundleURLSchemes</key><array><string>{scheme}</string></array>\n"
        "    </dict>\n  </array>\n"
    )


# The `Exec` and `MimeType` lines of a Linux desktop entry. With a scheme the
# program gets the link as its argument, `%u`, and the entry says it opens the
# links of the scheme.
def desktop_lines(binary: str, scheme: str | None) -> str:
    if scheme is None:
        return f"Exec={binary}\n"
    return f"Exec={binary} %u\nMimeType=x-scheme-handler/{scheme};\n"
