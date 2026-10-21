import pytest
from shared.android import fix_gradle, fix_manifest, limit_targets, replace_once
from shared.util import ScriptError

_GRADLE = """dependencies { implementation("androidx.games:games-activity:2.0.2") }
if (name == "javaPreCompileDebug" || name == "javaPreCompileRelease") {}
        getByName("debug") {
            jniLibs.srcDir("$buildDir/rustJniLibs/android")
        }
targets = listOf("x86_64", "x86", "arm", "arm64")
"""

_MANIFEST = "<manifest>\n    <application/>\n</manifest>\n"


def test_the_gradle_fixes_go_in_once():
    fixed = fix_gradle(_GRADLE)
    assert "games-activity:4.4.0" in fixed
    assert "mergeReleaseJniLibFolders" in fixed
    assert 'assets.srcDir("../../../assets")' in fixed
    assert fix_gradle(fixed) == fixed


def test_the_manifest_gets_the_permissions():
    fixed = fix_manifest(_MANIFEST, camera_permission="android.permission.CAMERA", multicast=True)
    assert "android.permission.INTERNET" in fixed
    assert "android.permission.CAMERA" in fixed
    assert "CHANGE_WIFI_MULTICAST_STATE" in fixed
    assert fixed.index("INTERNET") < fixed.index("<application")


def test_an_emulator_build_keeps_1_abi():
    assert 'targets = listOf("x86_64")' in limit_targets(_GRADLE, "x86_64")


def test_a_changed_template_is_an_error():
    with pytest.raises(ScriptError):
        replace_once("f", "nothing here", "old", "new")
    assert replace_once("f", "has new", "old", "new") == "has new"
