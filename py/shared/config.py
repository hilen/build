# The single source for project naming. hilen-mobile reads the same hilen.toml
# when it makes the mobile projects and derives the same casings from
# project_name, so these must match what it makes, or the paths the generated
# Xcode project uses do not line up.

from dataclasses import dataclass

import msgspec

from shared import toml
from shared.local_network import LocalNetwork, check
from shared.util import bail


class _Toml(msgspec.Struct, frozen=True):
    project_name: str | None = None
    bundle_id: str | None = None
    version: str = "1.0"
    ios_minimum_version: str = "13.0"
    tvos_minimum_version: str = "15.0"
    tvos: bool = False
    display_name: str | None = None
    infisical_project: str | None = None
    local_network: LocalNetwork | None = None


@dataclass(frozen=True, slots=True)
class Config:
    # cargo package name, and the Android lib name
    app_name: str
    # Xcode project, scheme and target name
    project_name: str
    # the staticlib cargo lipo makes, which the Xcode project links
    lib_name: str
    bundle_id: str
    # CFBundleShortVersionString of the iOS build. hilen-mobile bakes 1.0 into the
    # generated Info.plist with no knob, so the build patches it from this. The
    # App Store rejects an upload whose version is not above the live one.
    version: str
    # The minimum iOS of every generated Xcode configuration. App Store Connect
    # rejects an upload below iOS 13.
    ios_minimum_version: str
    # The minimum tvOS, for the Rust libs and the generated Xcode project.
    tvos_minimum_version: str
    # The app also ships for an Apple TV, `tvos = true`. `make fly` then uploads a
    # tvOS build too.
    tvos: bool
    # The name under the icon on a phone or a TV. Without it the system shows
    # project_name. Apple refuses an upload whose name is taken by an app of its
    # own, like Wallet.
    display_name: str | None
    # The Infisical project of the app. A phone build reads its HILEN_SESSION_KEY
    # from there.
    infisical_project: str | None
    # For an app that finds devices on the local network.
    local_network: LocalNetwork | None

    # The `CFBundleName` of an Apple build. Xcode names the exported ipa after
    # it, so the upload looks for this name.
    def bundle_name(self) -> str:
        return self.display_name or self.project_name


# Splits a name into lowercase words on dashes, underscores and camel humps, so
# the casing works whatever style hilen.toml uses.
def words(name: str) -> list[str]:
    spaced: list[str] = []
    previous_lower = False
    for c in name:
        if c.isascii() and c.isupper() and previous_lower:
            spaced.append(" ")
        previous_lower = c.isascii() and (c.islower() or c.isdigit())
        spaced.append(c)
    text = "".join(spaced).replace("-", " ").replace("_", " ")
    return [w.lower() for w in text.split(" ") if w]


# Read from the repo root. Several scripts chdir into mobile/iOS partway through,
# so read this before that, not lazily after.
def read() -> Config:
    return parse(toml.read_text())


def parse(text: str) -> Config:
    found = toml.decode(text, _Toml, "hilen.toml")
    if found.project_name is None:
        bail("project_name not found in hilen.toml")
    if found.bundle_id is None:
        bail("bundle_id not found in hilen.toml")
    parts = words(found.project_name)
    return Config(
        app_name="-".join(parts),
        project_name="".join(w[:1].upper() + w[1:] for w in parts),
        lib_name=f"lib{'_'.join(parts)}.a",
        bundle_id=found.bundle_id,
        version=found.version,
        ios_minimum_version=found.ios_minimum_version,
        tvos_minimum_version=found.tvos_minimum_version,
        tvos=found.tvos,
        display_name=found.display_name or None,
        infisical_project=found.infisical_project or None,
        local_network=None if found.local_network is None else check(found.local_network),
    )
