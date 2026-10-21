# Reading the output of a UI test lane: its counts and the report of each failed
# test, which ui-test.py saves 1 file per test.

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

LOG_DIR: Final = "target/ui-test"
_DESKTOP_PASSED: Final = re.compile(r"(\d+) UI tests passed")
_DESKTOP_FAILED: Final = re.compile(r"(\d+) of (\d+) UI test\(s\) failed")
_IOS_RESULT: Final = re.compile(r"(\d+) tests, (\d+) failed")


@dataclass(frozen=True, slots=True)
class Lane:
    name: str
    passed: int
    failed: int
    ok: bool
    log: Path
    # Failed test names with the path of the saved report.
    failures: tuple[tuple[str, Path], ...]


def slug(name: str) -> str:
    return name.strip().replace(" ", "_")


def log_path(lane: str) -> Path:
    return Path(LOG_DIR) / f"{slug(lane)}.log"


# A report of a failed test starts with a header line, "===== Name =====" from
# the desktop runner and "TEST FAILED: Name" from an app on a device.
def failure_header(line: str) -> str | None:
    if line.startswith("===== ") and line.endswith(" ====="):
        return line.removeprefix("===== ").removesuffix(" =====")
    if line.startswith("TEST FAILED: "):
        return line.removeprefix("TEST FAILED: ")
    return None


def split_failures(output: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    name: str | None = None
    body: list[str] = []
    for line in output.splitlines():
        header = failure_header(line)
        if header is not None:
            if name is not None:
                found.append((name, "".join(body)))
            name = header
            body = []
        elif name is not None:
            body.append(f"{line}\n")
    if name is not None:
        found.append((name, "".join(body)))
    return found


# Each block is saved on its own, so a failure is 1 file away.
def save_failures(lane: str, output: str) -> tuple[tuple[str, Path], ...]:
    folder = Path(LOG_DIR) / "failures" / slug(lane)
    saved: list[tuple[str, Path]] = []
    for name, body in split_failures(output):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{slug(name)}.txt"
        path.write_text(body, encoding="utf-8")
        saved.append((name, path))
    return tuple(saved)


# The desktop runner prints "N UI tests passed" on success and "M of N UI
# test(s) failed" otherwise.
def desktop_lane(name: str, output: str, *, ok: bool, log: Path) -> Lane:
    failures = save_failures(name, output)
    passed = _DESKTOP_PASSED.search(output)
    if passed is not None:
        return Lane(name, int(passed[1]), 0, ok=True, log=log, failures=failures)
    failed = _DESKTOP_FAILED.search(output)
    if failed is not None:
        bad, total = int(failed[1]), int(failed[2])
        return Lane(name, total - bad, bad, ok=False, log=log, failures=failures)
    return Lane(name, 0, 0, ok=ok, log=log, failures=failures)


# The iOS lane prints "N tests, M failed" in its ok and failed lines.
def ios_lane(output: str, *, ok: bool, log: Path) -> Lane:
    name = "iOS simulator"
    failures = save_failures(name, output)
    found = _IOS_RESULT.search(output)
    if found is None:
        return Lane(name, 0, 0, ok=ok, log=log, failures=failures)
    total, bad = int(found[1]), int(found[2])
    return Lane(name, total - bad, bad, ok=ok and bad == 0, log=log, failures=failures)
