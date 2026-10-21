# The update key of an app, which signs its releases for the engine updater.
# The secret is `<NAME>_UPDATE_KEY` in the env, 32 bytes hex, or the local key
# file ~/.config/<name>-hilen/update-key.hex when that is unset.

import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from shared.util import bail


def signing_key(name: str) -> Ed25519PrivateKey:
    env_name = f"{name.upper().replace('-', '_')}_UPDATE_KEY"
    hex_key = os.environ.get(env_name, "")
    if not hex_key.strip():
        path = Path(os.environ["HOME"]) / ".config" / f"{name}-hilen" / "update-key.hex"
        try:
            hex_key = path.read_text(encoding="utf-8")
        except OSError:
            bail(f"{env_name} not set and {path} not found")
    try:
        raw = bytes.fromhex(hex_key.strip())
    except ValueError:
        bail("update key is not hex")
    try:
        return Ed25519PrivateKey.from_private_bytes(raw)
    except ValueError as err:
        bail(f"update key: {err}")


def public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
