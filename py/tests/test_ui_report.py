from pathlib import Path
from typing import TYPE_CHECKING

from shared.ui_report import desktop_lane, failure_header, ios_lane, split_failures

if TYPE_CHECKING:
    import pytest

_OUTPUT = """starting
===== Button Test =====
expected red
got blue
TEST FAILED: Slider Test
off by 1
2 of 40 UI test(s) failed
"""


def test_the_header_of_a_report_names_the_test():
    assert failure_header("===== Button Test =====") == "Button Test"
    assert failure_header("TEST FAILED: Slider Test") == "Slider Test"
    assert failure_header("starting") is None


def test_each_failure_gets_its_own_body():
    assert split_failures(_OUTPUT) == [
        ("Button Test", "expected red\ngot blue\n"),
        ("Slider Test", "off by 1\n2 of 40 UI test(s) failed\n"),
    ]


def test_the_lanes_read_their_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "x.log"
    failed = desktop_lane("desktop debug", _OUTPUT, ok=False, log=log)
    assert (failed.passed, failed.failed, failed.ok) == (38, 2, False)
    assert (tmp_path / "target/ui-test/failures/desktop_debug/Button_Test.txt").is_file()
    passed = desktop_lane("desktop release", "40 UI tests passed\n", ok=True, log=log)
    assert (passed.passed, passed.failed, passed.ok) == (40, 0, True)
    ios = ios_lane("[ios] ok: 12 tests, 0 failed\n", ok=True, log=log)
    assert (ios.passed, ios.failed, ios.ok) == (12, 0, True)
