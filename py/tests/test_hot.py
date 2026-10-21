import os
from pathlib import Path

from shared.hot import System, first_device, middle_of_bmp, of_system

_SIZE = 3
_ROW = 12
_HEADER = 54


# 3 by 3 pixels of 3 bytes, rows filled up to 12 bytes, all black but the middle.
def test_the_middle_pixel_of_a_bmp_is_read():
    bmp = bytearray(_HEADER + _SIZE * _ROW)
    bmp[10] = _HEADER
    bmp[18] = _SIZE
    bmp[22] = _SIZE
    bmp[28] = 24
    middle = _HEADER + _ROW + _SIZE
    bmp[middle : middle + 3] = bytes([10, 20, 30])
    assert middle_of_bmp(bytes(bmp)) == (30, 20, 10)


def test_the_engine_folder_is_named_from_the_repo_of_an_app():
    assert os.path.relpath(Path("/dev/hilen/hilen"), Path("/dev/apps/skaityk")) == (
        "../../hilen/hilen"
    )


def test_a_device_id_is_read_from_a_simctl_line():
    text = "-- iOS 16.4 --\n    iPhone 8 (81A051F7-CB2B-47D2-80FA-8F0AB4CC8B02) (Booted)"
    assert first_device(text) == "81A051F7-CB2B-47D2-80FA-8F0AB4CC8B02"
    assert first_device("== Devices ==\n-- iOS 16.4 --") is None


def test_a_device_id_is_read_after_brackets_in_the_name():
    text = (
        "    Apple TV 4K (3rd generation) (at 1080p) "
        "(FB419527-D3BD-4E88-ACCA-016313DD9C08) (Shutdown)"
    )
    assert first_device(text) == "FB419527-D3BD-4E88-ACCA-016313DD9C08"


def test_the_booted_devices_are_split_by_system():
    text = """== Devices ==
-- iOS 16.4 --
    iPhone 8 (81A051F7-CB2B-47D2-80FA-8F0AB4CC8B02) (Booted)
-- tvOS 26.2 --
    te-AppleTV-26.2 (D54028A6-1D59-4BEF-9387-C596548D148E) (Booted)"""
    assert first_device(of_system(text, tv=True)) == "D54028A6-1D59-4BEF-9387-C596548D148E"
    assert first_device(of_system(text, tv=False)) == "81A051F7-CB2B-47D2-80FA-8F0AB4CC8B02"


def test_the_word_for_an_apple_tv_is_taken_off_the_arguments():
    args = ["tv", "start"]
    assert System.take(args) is System.TVOS
    assert args == ["start"]
    assert System.take(args) is System.IOS
    assert args == ["start"]
