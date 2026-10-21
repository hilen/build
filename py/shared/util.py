import io
import re
import sys
from collections.abc import Callable
from types import TracebackType
from typing import NoReturn


def eprint(message: str, *, end: str = "\n"):
    print(message, file=sys.stderr, end=end)


class ScriptError(Exception):
    pass


# Like `bail!`, the error goes up to `run_main` unless a caller handles it.
def bail(message: str) -> NoReturn:
    raise ScriptError(message)


# A regex group as a real str, ty rejects the `str | Any` of `Match.group`.
def group(found: re.Match[str], n: int) -> str:
    value = found.group(n)
    if not isinstance(value, str):
        bail(f"regex group {n} did not match")
    return value


def _report(kind: type[BaseException], error: BaseException, _trace: TracebackType | None):
    if issubclass(kind, KeyboardInterrupt):
        return
    eprint(f"Error: {error}")


# Every script ends in this. An error nothing handled prints `Error: <message>`
# and exits with 1, the way anyhow ends a Rust main, with no traceback.
def run_main(main: Callable[[], int]) -> NoReturn:
    sys.excepthook = _report
    # A make target or a CI log shows each line as it comes, like Rust stdout.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
