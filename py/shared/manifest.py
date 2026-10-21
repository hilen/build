# The manifests of a release: dist/manifest.json for the website and
# dist/updater.json for the engine updater, plus dist/<daemon>-updater.json for
# each daemon.

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import msgspec

from shared.util import eprint

if TYPE_CHECKING:
    from shared.release import Release

# The suffix of an artifact, the name of the file when it is there.
type Has = Callable[[str], str | None]


class Meta(msgspec.Struct, frozen=True):
    size: int
    sha256: str
    sig: str


class _Platform(msgspec.Struct, frozen=True):
    url: str
    size: int
    sha256: str
    sig: str


class _Updater(msgspec.Struct, frozen=True):
    version: str
    notes: str
    platforms: dict[str, _Platform]


class _Arches(msgspec.Struct, frozen=True, omit_defaults=True):
    x64: str | None = None
    arm64: str | None = None


class _LinuxArch(msgspec.Struct, frozen=True, omit_defaults=True):
    deb: str | None = None
    appimage: str | None = None


class _Linux(msgspec.Struct, frozen=True):
    x64: _LinuxArch
    arm64: _LinuxArch


# The fields go out in this order, like the struct of the first version.
class _Site(msgspec.Struct, frozen=True, omit_defaults=True, kw_only=True):
    version: str
    mac: str | None = None
    win: _Arches
    linux: _Linux


def pretty(value: msgspec.Struct) -> str:
    return msgspec.json.format(msgspec.json.encode(value), indent=2).decode()


def site(r: Release, has: Has) -> str:
    return pretty(
        _Site(
            version=r.version,
            mac=has(f"mac-{r.mac_arch()}.dmg"),
            win=_Arches(x64=has("windows-x64-setup.exe"), arm64=has("windows-arm64-setup.exe")),
            linux=_Linux(
                x64=_LinuxArch(deb=has("linux-x64.deb"), appimage=has("linux-x64.AppImage")),
                arm64=_LinuxArch(
                    deb=has("linux-aarch64.deb"), appimage=has("linux-aarch64.AppImage")
                ),
            ),
        )
    )


# The manifest key of each platform and the artifact suffix that serves it. The
# mac binary serves every mac target it was built for, both keys when it is
# universal.
def bare_entries(r: Release) -> list[tuple[str, str]]:
    mac = f"macos-{r.mac_arch()}"
    # The cpu is the first word of a target, `aarch64-apple-darwin`.
    entries = [(f"macos-{t.split('-', 1)[0]}", mac) for t in r.mac_targets if "-" in t]
    return [
        *entries,
        ("windows-x86_64", "windows-x64.exe"),
        ("windows-aarch64", "windows-arm64.exe"),
        ("linux-x86_64", "linux-x86_64"),
        ("linux-aarch64", "linux-aarch64"),
    ]


APPIMAGES = (
    ("linux-x86_64-appimage", "linux-x64.AppImage"),
    ("linux-aarch64-appimage", "linux-aarch64.AppImage"),
)


# Linux gets the bare binary and the AppImage under its own key, the engine
# picks by how the app runs. A deb install in /usr/bin is not user writable, the
# engine offers it no update, those users update through apt. None when no
# signed artifact is there.
def updater(
    r: Release,
    version: str,
    entries: Sequence[tuple[str, str]],
    has: Has,
    read: Callable[[str], str | None],
) -> str | None:
    platforms: dict[str, _Platform] = {}
    for key, suffix in entries:
        name = has(suffix)
        if name is None:
            continue
        meta_path = f"dist/{name}.meta.json"
        text = read(meta_path)
        if text is None:
            eprint(f"warn: {meta_path} missing, {key} left out of the manifest")
            continue
        meta = msgspec.json.decode(text, type=Meta)
        platforms[key] = _Platform(f"{r.download_url}/{name}", meta.size, meta.sha256, meta.sig)
    if not platforms:
        return None
    return pretty(_Updater(version, "", dict(sorted(platforms.items()))))
