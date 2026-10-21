import subprocess

import pytest
from shared.config import parse, words
from shared.local_network import INSPECT_SERVICE, LocalNetwork, plist_keys
from shared.secrets import SESSION_KEY_ENV, far_job, masked
from shared.util import ScriptError

from shared import biometric, bluetooth, camera, links

_APP = 'project_name = "turnscan"\nbundle_id = "vladas.turnscan"\n'


def _network(text: str) -> LocalNetwork | None:
    return parse(_APP + text).local_network


def test_no_table_no_network():
    assert _network("") is None
    assert plist_keys(None, inspect=False) is None


def test_the_network_table_is_read_and_checked():
    network = _network(
        '[local_network]\nservices = ["_turnscan._tcp"]\nusage = "Finds the boards."\n'
    )
    assert network == LocalNetwork(("_turnscan._tcp",), "Finds the boards.")


@pytest.mark.parametrize(
    "table",
    [
        'services = []\nusage = "x"\n',
        'services = ["turnscan"]\nusage = "x"\n',
        'services = ["_turnscan._tcp.local."]\nusage = "x"\n',
        'services = ["_turnscan._tcp"]\nusage = " "\n',
        'services = ["_turnscan._tcp"]\n',
        'services = ["_turnscan._tcp"]\nusage = "x"\nother = 1\n',
    ],
)
def test_a_wrong_network_table_is_an_error(table: str):
    with pytest.raises(ScriptError):
        _network(f"[local_network]\n{table}")


def test_the_inspect_service_joins_the_ones_of_the_app():
    network = LocalNetwork(("_turnscan._tcp",), "Finds the boards.")
    assert plist_keys(network, inspect=True) == (
        ["_turnscan._tcp", INSPECT_SERVICE],
        "Finds the boards.",
    )
    assert plist_keys(network, inspect=False) == (["_turnscan._tcp"], "Finds the boards.")
    keys = plist_keys(None, inspect=True)
    assert keys is not None
    assert keys[0] == [INSPECT_SERVICE]
    assert "developer tools" in keys[1]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("turnscan", ["turnscan"]),
        ("MyShop", ["my", "shop"]),
        ("my_shop-app2", ["my", "shop", "app2"]),
    ],
)
def test_words(name: str, expected: list[str]):
    assert words(name) == expected


def test_config_casings():
    config = parse('project_name = "my_shop"\nbundle_id = "x.shop"\n')
    assert (config.app_name, config.project_name, config.lib_name) == (
        "my-shop",
        "MyShop",
        "libmy_shop.a",
    )
    assert config.version == "1.0"
    assert config.bundle_name() == "MyShop"


def test_links():
    assert links.scheme_of('project_name = "shopping"') is None
    toml = 'project_name = "My_Shop"\n[links]\ndomains = ["shop.example.com"]\n'
    assert links.scheme_of(toml) == "my-shop"
    assert links.scheme_of('project_name = "shop"\n[links]\nscheme = "shop-app"\n') == "shop-app"
    lines = links.plist_lines("shopping", "vladas.shopping")
    assert "<key>CFBundleURLSchemes</key><array><string>shopping</string></array>" in lines
    assert "<string>vladas.shopping</string>" in lines
    assert (
        links.desktop_lines("shopping", "shopping")
        == "Exec=shopping %u\nMimeType=x-scheme-handler/shopping;\n"
    )
    assert links.desktop_lines("shopping", None) == "Exec=shopping\n"


@pytest.mark.parametrize("scheme", ["Shop", "1shop", "shop app", "https", ""])
def test_a_wrong_scheme_is_an_error(scheme: str):
    with pytest.raises(ScriptError):
        links.scheme_of(f'project_name = "shop"\n[links]\nscheme = "{scheme}"\n')


def test_biometric():
    toml = 'project_name = "wallet"\n[biometric]\nusage = " Face ID confirms each payment. "\n'
    assert biometric.usage_of(toml) == "Face ID confirms each payment."
    assert biometric.usage_of('project_name = "wallet"\n') is None
    for wrong in (
        "[biometric]\n",
        '[biometric]\nusage = "  "\n',
        '[biometric]\nusage = "a"\nother = 1\n',
    ):
        with pytest.raises(ScriptError):
            biometric.usage_of(wrong)


def test_bluetooth():
    assert bluetooth.usage_of('project_name = "turnscan"') is None
    toml = 'project_name = "turnscan"\n[bluetooth]\nusage = "Drives the turntable."\n'
    assert bluetooth.usage_of(toml) == "Drives the turntable."
    for wrong in (
        "[bluetooth]",
        '[bluetooth]\nusage = " "',
        '[bluetooth]\nusage = "x"\nscan = true',
    ):
        with pytest.raises(ScriptError):
            bluetooth.usage_of(wrong)
    assert bluetooth.plist_lines("Scans <boards> & lights") == (
        "  <key>NSBluetoothAlwaysUsageDescription</key>"
        "<string>Scans &lt;boards&gt; &amp; lights</string>\n"
    )


def test_camera():
    toml = 'project_name = "scan"\n[camera]\nusage = "Photos of <the> object & more"\n'
    usage = camera.usage_of(toml)
    assert usage == "Photos of <the> object & more"
    assert camera.plist_lines(usage) == (
        "  <key>NSCameraUsageDescription</key>"
        "<string>Photos of &lt;the&gt; object &amp; more</string>\n"
    )
    assert camera.usage_of('project_name = "scan"\n') is None
    with pytest.raises(ScriptError):
        camera.usage_of('[camera]\nusage = "  "\n')


def test_the_job_line_never_holds_the_key():
    job = far_job("cargo lipo -p app --release", "secret-key-value")
    assert "secret-key-value" not in job
    assert "read -r HILEN_SESSION_KEY" in job
    assert "HILEN_RELEASE=1" in job
    plain = far_job("cargo lipo -p app --release", None)
    assert "HILEN_SESSION_KEY" not in plain
    assert "export HILEN_RELEASE=1 && cargo lipo" in plain


def _masked(cmd: str, key: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["bash", "-c", masked(cmd)], env={SESSION_KEY_ENV: key}, capture_output=True, check=False
    )


def test_the_mask_hides_the_key_and_keeps_the_exit_code():
    key = "0123abcd"
    shown = _masked('echo HILEN_SESSION_KEY="$HILEN_SESSION_KEY" and more', key)
    assert shown.stdout.decode().strip() == "HILEN_SESSION_KEY=[hidden] and more"
    assert shown.returncode == 0
    failed = _masked("echo $HILEN_SESSION_KEY >&2; exit 3", key)
    assert key not in failed.stdout.decode()
    assert failed.returncode != 0
