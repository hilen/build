# hilen.toml read into typed structs. Each table module gives its own struct, a
# field this does not know is left alone.

from pathlib import Path

import msgspec

from shared.util import bail


def read_text() -> str:
    try:
        return Path("hilen.toml").read_text(encoding="utf-8")
    except OSError:
        bail("hilen.toml not found, run this from the repo root")


def decode[T](text: str, kind: type[T], what: str) -> T:
    try:
        return msgspec.toml.decode(text, type=kind)
    except msgspec.MsgspecError as err:
        bail(f"{what} in hilen.toml: {err}")
