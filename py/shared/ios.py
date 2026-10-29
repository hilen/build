# What every xcodebuild of an iOS app passes, and the name an Apple app shows
# under its icon.

import subprocess
from typing import Final

from shared.util import bail

# The linker flags of the app. A setting on the command line replaces the one of
# the project, so every xcodebuild call passes all of them.
#
# The 2 weak frameworks carry modern data constants. On iOS 12 and 13 dyld binds
# a strong data symbol eagerly, so a constant the device lacks, like
# kCGColorSpaceExtendedDisplayP3 or kSecUseDataProtectionKeychain, kills the app
# before main. Weak linking makes the missing constant NULL instead.
#
# The rest is what the engine needs linked and a static library can't ask for by
# itself: the video decode of ffmpeg, zlib for it, MediaPlayer for the lock
# screen controls, LocalAuthentication for Touch ID and Face ID, and the C++
# library and CoreML for the static sherpa-onnx and onnxruntime of `speech`.
LDFLAGS: Final = (
    "-Wl,-weak_framework,CoreGraphics -Wl,-weak_framework,Security "
    "-framework VideoToolbox -framework CoreMedia -framework CoreVideo -framework MediaPlayer "
    "-framework LocalAuthentication -framework CoreML -lz -lc++"
)


def _buddy(command: str, plist: str) -> bool:
    done = subprocess.run(
        ["/usr/libexec/PlistBuddy", "-c", command, plist], capture_output=True, check=False
    )
    return done.returncode == 0


# Writes the name into `CFBundleDisplayName` and `CFBundleName` of a generated
# Info.plist. Apple checks both against the names of its own apps, so a bundle
# name left at the project name still fails with 90129. The template has no
# display name key, so it is added, or set when an earlier run added it. The
# name goes past the shell, it may hold spaces.
def write_display_name(plist: str, name: str | None):
    if name is None:
        return
    for key in ("CFBundleDisplayName", "CFBundleName"):
        if not _buddy(f"Set :{key} {name}", plist) and not _buddy(
            f"Add :{key} string {name}", plist
        ):
            bail(f"{key} did not go into {plist}")
        print(f"{key} {name}")
