# 1 session at a time sends apps to the loader of a device, `make device`. On
# 2026-10-17 a second agent session swapped its own app onto a phone in the
# middle of a test of another one, and 2 bugs looked like 1.
#
# The lock is a file per device on this Mac. It names the agent session that
# holds it and the pid of that agent. It is free again when that agent no
# longer runs, or after `make device args=release`. A person at a terminal,
# with no agent above the command, always takes it, and is told whose it was.

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

from shared.run import probe
from shared.util import bail

_ANCESTORS: Final = 40
_AGENTS: Final = ("claude", "codex")
_SESSION_VARS: Final = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID")
_HOLDER_LINES: Final = 2


# Who sends the app, an agent session or a person at a terminal.
@dataclass(frozen=True, slots=True)
class Holder:
    # The session id of the agent, empty for a person.
    session: str
    # The pid of the agent, 0 for a person.
    pid: int
    # The app folder it sent.
    app: str

    def to_text(self) -> str:
        return f"{self.session}\n{self.pid}\n{self.app}\n"

    @classmethod
    def from_text(cls, text: str) -> Self | None:
        lines = text.splitlines()
        if len(lines) < _HOLDER_LINES:
            return None
        try:
            pid = int(lines[1].strip())
        except ValueError:
            return None
        return cls(lines[0], pid, lines[2] if len(lines) > _HOLDER_LINES else "")

    def is_person(self) -> bool:
        return self.pid == 0

    def same_agent(self, other: Self) -> bool:
        if not self.session or not other.session:
            return self.pid == other.pid
        return self.session == other.session

    def name(self) -> str:
        if self.is_person():
            return "a person at a terminal"
        return f"the agent session {self.session} with pid {self.pid}"


def _lock_path(device: str) -> Path:
    return Path(os.environ["HOME"]) / ".cache/hilen/device-locks" / device


def is_agent(command: str) -> bool:
    return Path(command.strip()).name in _AGENTS


# The parent pid and the command of a line of `ps -o ppid=,comm=`.
def parse_ps(line: str) -> tuple[int, str] | None:
    parts = line.strip().split(None, 1)
    if len(parts) != _HOLDER_LINES:
        return None
    try:
        return int(parts[0]), parts[1].strip()
    except ValueError:
        return None


# The nearest claude or codex process above this one.
def _agent_pid(pid: int) -> int | None:
    for _ in range(_ANCESTORS):
        found = parse_ps(probe(f"ps -o ppid=,comm= -p {pid}"))
        if found is None:
            return None
        parent, command = found
        if is_agent(command):
            return pid
        if parent <= 1:
            return None
        pid = parent
    return None


def _alive(pid: int) -> bool:
    return is_agent(probe(f"ps -o comm= -p {pid}"))


def _me(app: str) -> Holder:
    pid = _agent_pid(os.getpid())
    if pid is None:
        return Holder("", 0, app)
    session = next((v for name in _SESSION_VARS if (v := os.environ.get(name, ""))), "")
    return Holder(session, pid, app)


# Takes the loader of the device for this session, or stops when another
# running agent session holds it.
def take(device: str, app: str):
    path = _lock_path(device)
    me = _me(app)
    try:
        held = Holder.from_text(path.read_text(encoding="utf-8"))
    except OSError:
        held = None
    if held is not None and not held.is_person() and not held.same_agent(me) and _alive(held.pid):
        if not me.is_person():
            bail(
                f"the loader of this device is held by {held.name()} for {held.app}. It is free "
                "when that agent stops, or after `make device args=release` from that session. "
                "Ask the owner of the device before anything else"
            )
        print(f"[lock] {held.name()} held the loader for {held.app}, a person takes it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(me.to_text(), encoding="utf-8")


# Frees the loader of the device for any session.
def release(device: str):
    _lock_path(device).unlink(missing_ok=True)
    print("[lock] the loader of this device is free")
