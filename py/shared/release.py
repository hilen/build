# What the desktop release scripts need. The package comes from project_name in
# hilen.toml, its version and binary name from cargo metadata, the rest from the
# `[release]` table of hilen.toml. Asking cargo keeps this right for a
# workspace, where the version sits in `[workspace.package]` and the window app
# binary can carry another name than its package.

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import msgspec

from shared import bluetooth, camera, cargo, config, links, toml
from shared.run import run
from shared.util import ScriptError, bail

if TYPE_CHECKING:
    from shared.cargo import Package

_DOWNLOAD_HOST: Final = "https://get.vladas.xyz"
_DOWNLOAD_DEPLOYMENT: Final = "get"
_UNIVERSAL: Final = ("aarch64-apple-darwin", "x86_64-apple-darwin")


# A second product of an app, a binary with no window that updates itself with
# `hilen-updater`, like a daemon. It ships as 1 signed bare binary per platform,
# no bundle, no installer, with its own manifest next to the one of the app.
# Named in `daemons` of the `[release]` table by its package name.
@dataclass(frozen=True, slots=True)
class Daemon:
    # cargo package name, the artifact file name prefix
    name: str
    # the binary target of that package, the file name cargo builds
    bin: str
    version: str

    # `banda-daemon-0.2.0-macos-universal` style names.
    def artifact(self, suffix: str) -> str:
        return f"{self.name}-{self.version}-{suffix}"

    # The manifest of this daemon, next to the `updater.json` of the app.
    def manifest(self) -> str:
        return f"{self.name}-updater.json"


@dataclass(frozen=True, slots=True)
class Release:
    # cargo package name, the artifact file name prefix
    name: str
    # the binary target of that package, the file name cargo builds
    bin: str
    version: str
    bundle_id: str
    # where the binaries are served, no trailing slash
    download_url: str
    # the beekeeper deployment whose data/download/ holds the binaries
    host_deployment: str
    # the folder under that data/download/
    target_subdir: str
    # the targets of the mac build, 2 are glued into a universal binary
    mac_targets: tuple[str, ...]
    # false for an app without the engine updater, its binaries are not signed
    self_update: bool
    daemons: tuple[Daemon, ...]
    # the url scheme of the `[links]` table, registered by the packaging
    link_scheme: str | None
    # the text of the `[camera]` table, the packaging asks for the camera
    camera_usage: str | None
    # the text of the `[bluetooth]` table, macOS shows it when it asks for it
    bluetooth_usage: str | None

    # `kukareker-0.2.0-mac-universal.dmg` style names.
    def artifact(self, suffix: str) -> str:
        return f"{self.name}-{self.version}-{suffix}"

    # The word for the mac build in an artifact name, `universal` for the 2
    # targets together, else the cpu of the 1 target.
    def mac_arch(self) -> str:
        match self.mac_targets:
            case (_, _):
                return "universal"
            case ("aarch64-apple-darwin",):
                return "arm64"
            case ("x86_64-apple-darwin",):
                return "x64"
            case other:
                msg = f"mac_targets in hilen.toml must name 1 or 2 mac targets, got {list(other)}"
                raise ScriptError(msg)

    # Signs `files` for the updater, nothing for an app without it.
    def sign(self, files: Sequence[str]):
        if self.self_update:
            run(f"uv run -q --no-dev build/release/sign.py {' '.join(files)}")


# Every field can be left out. The download host fields then point at the
# central download server, the `get` deployment, with the app name as the
# folder. An app that still ships from another deployment names it here.
class _Distribution(msgspec.Struct, frozen=True):
    download_url: str | None = None
    host_deployment: str | None = None
    target_subdir: str | None = None
    self_update: bool = True
    mac_targets: tuple[str, ...] = _UNIVERSAL
    daemons: tuple[str, ...] = ()


class _Toml(msgspec.Struct, frozen=True):
    release: _Distribution


# A binary named like the package is the one to ship, side binaries such as a
# gallery are ignored. A lone binary under another name is it too, a workspace
# needs that when another crate owns the package name.
def pick_bin(package: Package) -> str:
    bins = [t.name for t in package.targets if "bin" in t.kind]
    if package.name in bins:
        return package.name
    if len(bins) == 1:
        return bins[0]
    msg = (
        f"cannot pick the binary of package {package.name} to release, it has {len(bins)}: "
        f"{', '.join(bins)}"
    )
    raise ScriptError(msg)


def _package(found: tuple[Package, ...], name: str, why: str) -> Package:
    package = cargo.find(found, name)
    if package is None:
        bail(f"no cargo package named {name}, {why}")
    return package


# Read from the repo root, before any chdir.
def read() -> Release:
    app = config.read()
    text = toml.read_text()
    table = toml.decode(text, _Toml, "[release] table").release
    found = cargo.packages()
    daemons = tuple(
        Daemon(p.name, pick_bin(p), p.version)
        for p in (
            _package(found, name, "listed in daemons of hilen.toml") for name in table.daemons
        )
    )
    package = _package(found, app.app_name, "the project_name of hilen.toml")
    name = package.name
    return Release(
        name=name,
        bin=pick_bin(package),
        version=package.version,
        bundle_id=app.bundle_id,
        download_url=f"{_DOWNLOAD_HOST}/{name}"
        if table.download_url is None
        else table.download_url.rstrip("/"),
        host_deployment=table.host_deployment or _DOWNLOAD_DEPLOYMENT,
        target_subdir=table.target_subdir or name,
        mac_targets=table.mac_targets,
        self_update=table.self_update,
        daemons=daemons,
        link_scheme=links.scheme_of(text),
        camera_usage=camera.usage_of(text),
        bluetooth_usage=bluetooth.usage_of(text),
    )
