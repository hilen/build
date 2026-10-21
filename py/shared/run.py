# Running commands. Every command is a shell string, the way the make targets
# and the old scripts wrote them, so a pipe or a quoted argument keeps working
# without being taken apart into an argv. sh runs it, cmd on Windows, which gets
# the string untouched.

import shutil
import subprocess
import sys

from shared.util import bail, eprint


# A machine with no Rust toolchain has no cargo, its builds run on another
# machine through far.
def has(program: str) -> bool:
    return shutil.which(program) is not None


# cmd gets the string as it is. A list would wrap it in quotes with `\"` escapes,
# which cmd does not know, and split every quoted argument.
def _argv(cmd: str) -> list[str] | str:
    return f"cmd /C {cmd}" if sys.platform == "win32" else ["sh", "-c", cmd]


def _shell(
    cmd: str, *, piped: bool = False, both: bool = False, text_in: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        _argv(cmd),
        stdout=subprocess.PIPE if piped or both else None,
        stderr=subprocess.PIPE if both else None,
        input=text_in,
        check=False,
    )


# Echoes the command, runs it on the terminal, and fails on an error exit.
def run(cmd: str):
    print(cmd, flush=True)
    if _shell(cmd).returncode != 0:
        bail(f"command failed: {cmd}")


# An error exit is expected and ignored, for cleanup steps.
def run_allow_fail(cmd: str):
    print(cmd, flush=True)
    try:
        _shell(cmd)
    except OSError as err:
        print(f"ignoring: {err}")


# stdout is piped, not inherited, so a captured secret never reaches the log.
def capture(cmd: str) -> str:
    print(cmd, flush=True)
    out = _shell(cmd, piped=True)
    if out.returncode != 0:
        bail(f"command failed: {cmd}")
    return out.stdout.decode(errors="replace").strip()


# For a command that reads a secret from the environment. It is not echoed, so
# write the secret as a shell variable like `$TOKEN`, never as its value.
def run_secret(cmd: str):
    code = _shell(cmd).returncode
    if code != 0:
        bail(f"credentialed command failed with {code}")


# `input` and a line end go on its stdin, for a secret the command must not hold
# on its line.
def run_with_input(cmd: str, text: str):
    print(cmd, flush=True)
    if _shell(cmd, text_in=f"{text}\n".encode()).returncode != 0:
        bail(f"command failed: {cmd}")


# stdout and stderr together, never a failure, for a probe whose error exit is a
# normal answer.
def probe(cmd: str) -> str:
    try:
        out = _shell(cmd, both=True)
    except OSError:
        return ""
    return out.stdout.decode(errors="replace") + out.stderr.decode(errors="replace")


# The output shows only when the command fails, so a parallel lane does not mangle
# the output of another.
def run_quiet(cmd: str) -> str:
    out = _shell(cmd, both=True)
    text = out.stdout.decode(errors="replace") + out.stderr.decode(errors="replace")
    if out.returncode != 0:
        eprint(text, end="")
        bail(f"command failed: {cmd}")
    return text


def is_windows() -> bool:
    return sys.platform == "win32"
