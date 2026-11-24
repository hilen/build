from typing import Final

import pytest
from shared.sim import find_point, unescape, window_width
from shared.util import ScriptError

_WIDTH: Final = 402.0
_FOUND: Final = "Button.save: hilen::ui::Button 'Save'  [20, 100] 80x40  visible  save-button\n"


def test_the_middle_of_the_view_scales_to_screen_points():
    assert find_point(_FOUND, 0.5) == (30.0, 60.0)


def test_a_view_with_no_id_is_found():
    assert find_point("Label 'Hi'  [0, 0] 10x10  visible  \n", 1.0) == (5.0, 5.0)


def test_2_matches_are_refused():
    with pytest.raises(ScriptError, match="2 visible views match"):
        find_point(_FOUND + _FOUND, 1.0)


def test_the_width_of_the_main_window_is_read():
    assert window_width(f"0  {_WIDTH:g}x874  demo\n1  300x200  other\n") == _WIDTH


def test_a_dump_gets_its_line_ends_and_backslashes_back():
    assert unescape("a\\nb\\\\nc") == "a\nb\\nc"
