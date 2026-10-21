# The pending template fixes of the generated Android project, from
# docs/android.md. The template still misses them, so a new generation reverts
# them and they go in again after every one. Each skips quietly once the template
# itself carries the fix.

from collections.abc import Callable
from pathlib import Path
from typing import Final

from shared.local_network import MULTICAST_PERMISSION
from shared.util import bail

GRADLE: Final = "mobile/android/app/build.gradle.kts"
MANIFEST: Final = "mobile/android/app/src/main/AndroidManifest.xml"
PROPERTIES: Final = "mobile/android/gradle.properties"
_ALL_TARGETS: Final = 'targets = listOf("x86_64", "x86", "arm", "arm64")'
_APPLICATION: Final = "    <application"


# The fix present already is fine, the template landed it. Neither the old nor
# the new text found means the template changed shape and the fix needs a fresh
# look, so that fails loudly.
def replace_once(path: str, content: str, old: str, new: str) -> str:
    if new in content:
        return content
    if old not in content:
        bail(f"expected `{old}` in {path}")
    return content.replace(old, new)


def fix_gradle(content: str) -> str:
    # games-activity must match the version the android-activity crate bundles,
    # with 2.0.2 RegisterNatives aborts the process at startup.
    content = replace_once(
        GRADLE,
        content,
        "androidx.games:games-activity:2.0.2",
        "androidx.games:games-activity:4.4.0",
    )
    # Packaging can run before the fresh .so lands unless the jni merge tasks wait
    # for the cargo build.
    content = replace_once(
        GRADLE,
        content,
        'name == "javaPreCompileDebug" || name == "javaPreCompileRelease"',
        'name == "javaPreCompileDebug" || name == "javaPreCompileRelease" ||\n'
        '            name == "mergeDebugJniLibFolders" || name == "mergeReleaseJniLibFolders"',
    )
    # The assets folder of the repo rides into the APK, filesystem::read_bytes
    # reads it back through the AAssetManager.
    jni_debug = (
        '        getByName("debug") {\n'
        '            jniLibs.srcDir("$buildDir/rustJniLibs/android")\n'
        "        }"
    )
    with_assets = (
        f'{jni_debug}\n        getByName("main") {{\n'
        '            assets.srcDir("../../../assets")\n'
        "        }"
    )
    return replace_once(GRADLE, content, jni_debug, with_assets)


# The lines the manifest needs before its <application>, each only when missing.
def fix_manifest(content: str, *, camera_permission: str | None, multicast: bool) -> str:
    # Sockets are denied without the INTERNET permission, which fails the Rest
    # request test and the inspect listener.
    if "android.permission.INTERNET" not in content:
        content = replace_once(
            MANIFEST,
            content,
            _APPLICATION,
            f'    <uses-permission android:name="android.permission.INTERNET"/>\n\n{_APPLICATION}',
        )
    # The camera of an app with a `[camera]` table, the engine asks the user for it
    # while the app runs.
    if camera_permission is not None and camera_permission not in content:
        content = replace_once(
            MANIFEST,
            content,
            _APPLICATION,
            f'    <uses-permission android:name="{camera_permission}"/>\n'
            '    <uses-feature android:name="android.hardware.camera.any" '
            'android:required="false"/>\n\n'
            f"{_APPLICATION}",
        )
    # Wi-Fi drops multicast unless the app holds a multicast lock, which the mDNS
    # browse of an app with a [local_network] table takes.
    if multicast:
        content = replace_once(
            MANIFEST, content, _APPLICATION, f"    {MULTICAST_PERMISSION}\n\n{_APPLICATION}"
        )
    return content


# The generated project always lists all 4 ABIs. An emulator build needs only 1,
# so the fresh gradle config is trimmed after every generation.
def limit_targets(content: str, abi: str) -> str:
    if _ALL_TARGETS not in content:
        bail(f"expected targets line not found in {GRADLE}")
    return content.replace(_ALL_TARGETS, f'targets = listOf("{abi}")')


def edit(path: str, change: Callable[[str], str]):
    file = Path(path)
    file.write_text(change(file.read_text(encoding="utf-8")), encoding="utf-8")
