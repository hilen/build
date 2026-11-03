import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from mac import _info_plist, bundle
from shared.open_files import types_of
from shared.release import Release

if TYPE_CHECKING:
    import pytest


def _release(open_file_types: tuple[str, ...] = ()) -> Release:
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
        open_file_types=open_file_types,
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


def test_the_plist_names_the_file_types_and_keeps_the_default_app():
    plist = _info_plist(_release(("public.movie",)))

    assert "<key>CFBundleDocumentTypes</key>" in plist
    assert "<string>public.movie</string>" in plist
    assert "<key>LSHandlerRank</key><string>Alternate</string>" in plist


def test_an_app_with_no_file_types_has_no_document_types():
    assert "CFBundleDocumentTypes" not in _info_plist(_release())


def test_the_table_gives_the_types():
    assert types_of('[open_files]\ntypes = ["public.movie"]\n') == ("public.movie",)
    assert types_of('project_name = "x"\n') == ()
