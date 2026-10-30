import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from mac import bundle
from shared.release import Release

if TYPE_CHECKING:
    import pytest


def _release() -> Release:
    return Release(
        name="my-app",
        bin="my-app",
        version="1.0.0",
        bundle_id="my.app",
        download_url="https://example.com/my-app",
        host_deployment="get",
        target_subdir="my-app",
        mac_targets=("aarch64-apple-darwin",),
        self_update=True,
        daemons=(),
        link_scheme=None,
        camera_usage=None,
        bluetooth_usage=None,
        speech_usage=None,
    )


def test_the_binary_in_the_bundle_can_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/icon.icns").write_bytes(b"icon")
    binary = tmp_path / "my-app"
    binary.write_bytes(b"binary")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

    app = bundle(_release(), str(binary))

    assert os.access(f"{app}/Contents/MacOS/my-app", os.X_OK)
