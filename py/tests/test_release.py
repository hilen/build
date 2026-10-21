from pathlib import Path

import pytest
from shared.update_key import public_hex, signing_key
from shared.util import ScriptError

# Test 1 of RFC 8032, the signature of an empty message.
_RFC_PRIVATE_HEX = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
_PUBLIC = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
_SIGNATURE = (
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)


def test_the_key_signs_like_rfc_8032(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_APP_UPDATE_KEY", _RFC_PRIVATE_HEX)
    key = signing_key("my-app")
    assert public_hex(key) == _PUBLIC
    assert key.sign(b"").hex() == _SIGNATURE


def test_the_key_file_is_read_when_the_env_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MY_APP_UPDATE_KEY", " ")
    monkeypatch.setenv("HOME", str(tmp_path))
    folder = tmp_path / ".config/my-app-hilen"
    folder.mkdir(parents=True)
    (folder / "update-key.hex").write_text(f"{_RFC_PRIVATE_HEX}\n")
    assert public_hex(signing_key("my-app")) == _PUBLIC


def test_a_bad_key_is_an_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_APP_UPDATE_KEY", "zz")
    with pytest.raises(ScriptError):
        signing_key("my-app")
