# `cargo metadata` of the repo, read before any chdir.

import msgspec

from shared.run import capture
from shared.util import bail


class Target(msgspec.Struct, frozen=True):
    name: str
    kind: tuple[str, ...] = ()


class Package(msgspec.Struct, frozen=True):
    name: str
    version: str
    manifest_path: str = ""
    targets: tuple[Target, ...] = ()


class _Metadata(msgspec.Struct, frozen=True):
    packages: tuple[Package, ...] = ()


def packages() -> tuple[Package, ...]:
    text = capture("cargo metadata --no-deps --format-version 1")
    try:
        return msgspec.json.decode(text, type=_Metadata).packages
    except msgspec.MsgspecError as err:
        bail(f"cargo metadata: {err}")


def find(found: tuple[Package, ...], name: str) -> Package | None:
    return next((p for p in found if p.name == name), None)
