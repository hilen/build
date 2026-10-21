import pytest
from shared.mobile import drop_lipo_phase, set_deployment_target
from shared.util import ScriptError

_PROJECT = (
    "IPHONEOS_DEPLOYMENT_TARGET = 12.0;\nfoo\nIPHONEOS_DEPLOYMENT_TARGET = 12.0;\n"
    'shellScript = "~/.cargo/bin/cargo lipo --release\\n";\n'
)


def test_the_minimum_of_the_app_goes_over_every_configuration():
    out = set_deployment_target(_PROJECT, "IPHONEOS_DEPLOYMENT_TARGET", "13.0")
    assert "12.0" not in out
    assert "IPHONEOS_DEPLOYMENT_TARGET = 13.0;\nfoo\nIPHONEOS_DEPLOYMENT_TARGET = 13.0;" in out


def test_the_lipo_phase_is_emptied():
    assert 'shellScript = "true\\n";' in drop_lipo_phase(_PROJECT)


def test_a_project_without_the_setting_is_an_error():
    with pytest.raises(ScriptError):
        set_deployment_target("nothing", "TVOS_DEPLOYMENT_TARGET", "15.0")
    with pytest.raises(ScriptError):
        drop_lipo_phase("nothing")
