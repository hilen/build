# A paired iPhone, iPad or Apple TV that runs the hot loader, `make device`, see
# "A real device" in docs/hot-reload.md of hilen.
#
# The device is picked through `hilen-inspect devices`, which reads the list of
# Xcode. Every command for it then goes to that device by its id, never to
# whatever hot build a search of the network finds first.

import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Final, Self

from shared.hot import System, inspect_tool
from shared.run import capture, probe, run
from shared.util import ScriptError, bail

_TV_KIND: Final = "appleTV"
# A started loader needs a moment until it answers.
_WAKE_TRIES: Final = 20
_WAKE_POLL: Final = 1.0
# `hot-status` of a hot build names its library.
_HOT_MARK: Final = "library"
# `build-time` of any app that answers the inspector starts with this.
_APP_MARK: Final = "app code built"
# An app has to answer as no hot build this many times in a row before it is
# taken for one, a loader in its start may answer in between.
_PLAIN_TRIES: Final = 2
# An older tool prints no system, the address is always last.
_OLD_FIELDS: Final = 4


# What answers on a device after the start of the loader.
class Woke(Enum):
    # A hot build, it takes a library.
    HOT = auto()
    # An app that answers the inspector and is no hot build. No wait changes
    # that, the loader has to be installed again. Once such an app sat on a phone
    # and the send waited 90 seconds on it for nothing.
    PLAIN = auto()


# What the answers of the inspect tool say about the app in front, None while
# it does not answer at all.
def seen(status: str, build_time: str) -> Woke | None:
    if _HOT_MARK in status:
        return Woke.HOT
    if _APP_MARK in build_time:
        return Woke.PLAIN
    return None


@dataclass(frozen=True, slots=True)
class Device:
    # The id every `devicectl` command takes.
    id: str
    name: str
    # The system and its version, like `tvOS 26.3`.
    os: str
    system: System
    # An app on it answers the inspect tool.
    answers: bool
    inspect_path: Path

    # The paired device `word` names, by its id or by a part of its name or
    # kind. With no word it is the only paired device. `here` is the engine
    # repo, its inspect tool does the asking.
    @classmethod
    def pick(cls, here: Path, word: str | None) -> Self:
        tool = inspect_tool(here)
        flag = "" if word is None else f' --device "{word}"'
        listed = capture(f'"{tool}"{flag} devices')
        found = [cls.from_line(line, tool) for line in listed.splitlines()]
        if len(found) == 1:
            return found[0]
        if not found:
            bail("no paired device, plug it in, unlock it and tap Trust")
        msg = f"several paired devices, name 1 of them, like `make device args=tv`:\n{listed}"
        raise ScriptError(msg)

    # A line of `hilen-inspect devices`: the id, the kind, the name, the system
    # with its version and the address an app answers at, with a tab between.
    @classmethod
    def from_line(cls, line: str, tool: Path) -> Self:
        parts = line.split("\t")
        if len(parts) < _OLD_FIELDS:
            bail(f"`hilen-inspect devices` printed a line that is no device: {line}")
        return cls(
            id=parts[0],
            name=parts[2],
            os=parts[3] if len(parts) > _OLD_FIELDS else "",
            system=System.TVOS if parts[1] == _TV_KIND else System.IOS,
            answers=parts[-1] != "-",
            inspect_path=tool,
        )

    # The shell line of an inspect command for this device.
    def inspect(self, command: str) -> str:
        return f'"{self.inspect_path}" --device {self.id} {command}'

    def _ask(self) -> Woke | None:
        status = probe(self.inspect("hot-status"))
        build_time = "" if _HOT_MARK in status else probe(self.inspect("build-time"))
        return seen(status, build_time)

    # Starts the loader `bundle_id` when no hot build answers on the device, and
    # waits until one does.
    def wake(self, bundle_id: str) -> Woke:
        if self.answers and self._ask() is Woke.HOT:
            return Woke.HOT
        print(f"\n[device] no hot build answers on {self.name}, starting the loader")
        try:
            run(
                f"xcrun devicectl device process launch --device {self.id} "
                f"--terminate-existing {bundle_id}"
            )
        except ScriptError as err:
            bail(
                f"the loader did not start on {self.name}. Unlock the device. When the loader is "
                f"not on it, install it with `make device args=install`: {err}"
            )
        return self.wait()

    # Waits until the loader that was just started answers.
    def wait(self) -> Woke:
        plain = 0
        for _ in range(_WAKE_TRIES):
            time.sleep(_WAKE_POLL)
            match self._ask():
                case Woke.HOT:
                    return Woke.HOT
                case Woke.PLAIN:
                    plain += 1
                    if plain == _PLAIN_TRIES:
                        return Woke.PLAIN
                case None:
                    plain = 0
        msg = (
            f"the loader on {self.name} was started, but it does not answer. Keep the device "
            "unlocked with the loader in front"
        )
        raise ScriptError(msg)
