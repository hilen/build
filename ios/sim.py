#!/usr/bin/env -S uv run -q --no-dev

# 1 app in the iOS simulator of this Mac, driven 1 step at a time with real
# touches and the real screen keyboard, `make sim`. See ios-debug.md of the
# hilen skill.

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from shared.sim import Phone
from shared.util import ScriptError, bail, run_main

from shared import sim

_USAGE: Final = """1 app in the iOS simulator of this Mac with real touches and keys

  start [iphone8] [template <folder>]
                              build the app of this folder and its helper on a
                              builder, open it on an iPhone 17 Pro with iOS 26.3,
                              or an iPhone 8 with iOS 16.4. A template folder of
                              hilen-mobile replaces the one of its main branch
  tap <x> <y>                 a tap, in screen points
  tap view <query>            a tap on the middle of the 1 visible view that
                              `hilen-inspect find` finds
  double <x> <y> | double view <query>
  hold <x> <y> [seconds] | hold view <query>
  swipe <x> <y> <x> <y> [seconds]
                              a flick from the first point to the second
  drag <x> <y> <x> <y> [seconds held first]
                              a finger held, moved and rested before it lifts
  pinch <scale>               2 fingers at the middle, above 1 apart
  point <query>               the screen point a view tap would use
  type <text>                 taps the keys of the screen keyboard
  key return | key delete     1 key of the screen keyboard
  keyboard up | keyboard down waits until the keyboard is there or gone
  value                       the text of the system text field
  dump [system]               what the app shows, the keyboard included, or
                              what the system shows over it, like an alert
  shot [<path>]               a picture of the whole screen, prints its path
  steps <step> then <step> .. the steps in a row with no wait for the app to
                              stand still, like a swipe on a view that still
                              moves. A step is a tap, double, hold, swipe,
                              drag or pinch with numbers, or wait <seconds>
  reference [beside] [measure]
                              a real UIPageViewController with the pages of the
                              demo, in front on this device or on a second one
                              beside it. measure logs touches and page moves
  stop                        end the session"""

_MOVE_NUMBERS: Final = (4, 5)


def _refuse(words: Sequence[str]) -> ScriptError:
    return ScriptError(
        f"wrong words: {' '.join(words) or 'none'}, `make sim` alone prints the usage"
    )


def _number(text: str) -> str:
    try:
        float(text)
    except ValueError:
        bail(f"not a number: {text}")
    return text


def _numbers(texts: Sequence[str]) -> str:
    return " ".join(_number(text) for text in texts)


def _reference(root: Path, words: Sequence[str]):
    if any(word not in {"beside", "measure"} for word in words):
        raise _refuse(words)
    log = sim.reference(root, beside="beside" in words, measure="measure" in words)
    print(f"the log of the reference is {log}")


def _start(root: Path, words: Sequence[str]):
    phone = Phone.IPHONE_17_PRO
    template: Path | None = None
    rest = list(words)
    while rest:
        match rest:
            case ["iphone8", *tail]:
                phone, rest = Phone.IPHONE_8, tail
            case ["template", folder, *tail]:
                template, rest = Path(folder).resolve(), tail
            case _:
                raise _refuse(rest)
    sim.start(root, phone, template)


# A point of a step, given as 2 numbers or as `view <query>`.
def _point(root: Path, words: Sequence[str]) -> str:
    match words:
        case ["view", *query] if query:
            x, y = sim.view_point(root, " ".join(query))
            return f"{x:.1f} {y:.1f}"
        case [x, y]:
            return _numbers((x, y))
        case _:
            raise _refuse(words)


def _tap(root: Path, words: Sequence[str]) -> str:
    return sim.ask(root, f"tap {_point(root, words)}")


def _double(root: Path, words: Sequence[str]) -> str:
    return sim.ask(root, f"double {_point(root, words)}")


def _hold(root: Path, words: Sequence[str]) -> str:
    match words:
        case ["view", *_]:
            return sim.ask(root, f"hold {_point(root, words)}")
        case [x, y, *seconds] if len(seconds) <= 1:
            return sim.ask(root, f"hold {_numbers((x, y, *seconds))}")
        case _:
            raise _refuse(words)


def _move(root: Path, kind: str, words: Sequence[str]) -> str:
    if len(words) not in _MOVE_NUMBERS:
        raise _refuse(words)
    return sim.ask(root, f"{kind} {_numbers(words)}")


def _swipe(root: Path, words: Sequence[str]) -> str:
    return _move(root, "swipe", words)


def _drag(root: Path, words: Sequence[str]) -> str:
    return _move(root, "drag", words)


def _pinch(root: Path, words: Sequence[str]) -> str:
    match words:
        case [scale]:
            return sim.ask(root, f"pinch {_number(scale)}")
        case _:
            raise _refuse(words)


def _where(root: Path, words: Sequence[str]) -> str:
    if not words:
        raise _refuse(words)
    x, y = sim.view_point(root, " ".join(words))
    return f"{x:.1f} {y:.1f}"


def _type(root: Path, words: Sequence[str]) -> str:
    if not words:
        raise _refuse(words)
    return sim.ask(root, f"type {' '.join(words)}")


def _key(root: Path, words: Sequence[str]) -> str:
    match words:
        case [("return" | "delete") as key]:
            return sim.ask(root, f"key {key}")
        case _:
            raise _refuse(words)


def _keyboard(root: Path, words: Sequence[str]) -> str:
    match words:
        case ["up"]:
            return sim.ask(root, "keyboard 1")
        case ["down"]:
            return sim.ask(root, "keyboard 0")
        case _:
            raise _refuse(words)


def _value(root: Path, words: Sequence[str]) -> str:
    if words:
        raise _refuse(words)
    return sim.ask(root, "value")


def _dump(root: Path, words: Sequence[str]) -> str:
    match words:
        case []:
            return sim.unescape(sim.ask(root, "dump"))
        case ["system"]:
            return sim.unescape(sim.ask(root, "dump system"))
        case _:
            raise _refuse(words)


def _shot(root: Path, words: Sequence[str]) -> str:
    match words:
        case []:
            return str(sim.shot(root, None))
        case [path]:
            return str(sim.shot(root, Path(path)))
        case _:
            raise _refuse(words)


_IN_A_ROW: Final = frozenset({"tap", "double", "hold", "swipe", "drag", "pinch", "wait"})


def _in_a_row(root: Path, words: Sequence[str]) -> str:
    steps: list[str] = []
    step: list[str] = []
    for word in (*words, "then"):
        if word != "then":
            step.append(word)
            continue
        if not step or step[0] not in _IN_A_ROW:
            raise _refuse(step)
        steps.append(f"{step[0]} {_numbers(step[1:])}")
        step = []
    return sim.ask(root, f"batch {'; '.join(steps)}")


_STEPS: Final[dict[str, Callable[[Path, Sequence[str]], str]]] = {
    "tap": _tap,
    "double": _double,
    "hold": _hold,
    "swipe": _swipe,
    "drag": _drag,
    "pinch": _pinch,
    "point": _where,
    "type": _type,
    "key": _key,
    "keyboard": _keyboard,
    "value": _value,
    "dump": _dump,
    "shot": _shot,
    "steps": _in_a_row,
}


def main() -> int:
    args = sys.argv[1:]
    root = Path.cwd()
    match args:
        case ["start", *words]:
            _start(root, words)
        case ["stop"]:
            sim.stop(root)
        case ["reference", *words]:
            _reference(root, words)
        case [name, *words] if name in _STEPS:
            print(_STEPS[name](root, words) or "ok")
        case _:
            print(_USAGE)
            bail("no such command")
    return 0


if __name__ == "__main__":
    run_main(main)
