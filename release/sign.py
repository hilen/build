#!/usr/bin/env -S uv run -q --no-dev

# Signs release artifacts for the engine updater. Writes `<file>.meta.json` with
# the size, sha256 and ed25519 signature, the fields updater.json embeds per
# platform. The key comes from shared/update_key.py.

import hashlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import msgspec
from shared.update_key import public_hex, signing_key
from shared.util import bail, run_main

from shared import release

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_PUBLIC_KEY: Final = "assets/update-key.pub"


class _Meta(msgspec.Struct, frozen=True):
    size: int
    sha256: str
    sig: str


# A wrong secret would ship updates that no installed app accepts. An app that
# keeps its public key in assets/update-key.pub gets the secret checked against
# it.
def _check_public_key(key: Ed25519PrivateKey):
    try:
        public = Path(_PUBLIC_KEY).read_text(encoding="utf-8")
    except OSError:
        print(f"no {_PUBLIC_KEY}, the signing key is not checked against the app")
        return
    if public_hex(key) != public.strip():
        bail(f"the signing key does not match {_PUBLIC_KEY}, the public key embedded in the app")


def main() -> int:
    name = release.read().name
    files = sys.argv[1:]
    if not files:
        bail("usage: sign.py <artifact> [<artifact> ...]")
    key = signing_key(name)
    _check_public_key(key)
    for file in files:
        try:
            data = Path(file).read_bytes()
        except OSError as err:
            bail(f"read {file}: {err}")
        meta = _Meta(len(data), hashlib.sha256(data).hexdigest(), key.sign(data).hex())
        out = f"{file}.meta.json"
        Path(out).write_bytes(msgspec.json.format(msgspec.json.encode(meta), indent=2))
        print(f"signed {file} -> {out}")
    return 0


if __name__ == "__main__":
    run_main(main)
