# What the tvOS scripts share.

from typing import Final

DEVICE: Final = "aarch64-apple-tvos"
SIMULATOR: Final = "aarch64-apple-tvos-sim"


# The release staticlib of a target, the path the Xcode project links from.
def lib(target: str, lib_name: str) -> str:
    return f"target/{target}/release/{lib_name}"
