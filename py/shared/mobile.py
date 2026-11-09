# What the iOS and the tvOS project builds share: hilen-mobile makes the Xcode
# project, then the settings of the app go over the ones of its template.

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from shared.run import has, run
from shared.util import bail

# The generator is built from main of its repo on every run, cargo builds it again
# only when main moved. The crates.io copy and a hand built one went stale: on
# 2026-11-09 both lacked the widget and Siri tables, and a fly shipped without them.
_INSTALL: Final = (
    "cargo install --git https://github.com/hilen/hilen-mobile --branch main --locked hilen-mobile"
)
# In the build folder of the app, on the builder and here.
_FAR_ROOT: Final = "target/hilen-mobile"


@dataclass(frozen=True, slots=True)
class Generator:
    steps: tuple[str, ...]
    program: str


def generator(*, cargo: bool) -> Generator:
    if cargo:
        return Generator(steps=(_INSTALL,), program="hilen-mobile")
    # A machine with no Rust toolchain gets it built on a mac builder.
    return Generator(
        steps=(
            f"far --on mac '{_INSTALL} --root {_FAR_ROOT}'",
            f"far --on mac get {_FAR_ROOT}/bin/hilen-mobile",
        ),
        program=f"./{_FAR_ROOT}/bin/hilen-mobile",
    )


def generate(args: Sequence[str]):
    os.environ.pop("CFLAGS", None)
    os.environ.pop("CXXFLAGS", None)
    found = generator(cargo=has("cargo"))
    for step in found.steps:
        run(step)
    run(f"{found.program} {' '.join(args)}".strip())


# The template of the generator has its own deployment target. The minimum of the
# app goes over it after every generation, for local builds and fly.
def set_deployment_target(project: str, key: str, version: str) -> str:
    pattern = re.compile(rf"{key} = [0-9.]+;")
    if pattern.search(project) is None:
        bail(f"generated Xcode project has no {key}")
    return pattern.sub(f"{key} = {version};", project)


# The template has a build phase that runs `~/.cargo/bin/cargo lipo` on archive.
# With no cargo here the archive would stop there. The lib is built and fresh
# already, so the phase is emptied.
def drop_lipo_phase(project: str) -> str:
    pattern = re.compile(r'shellScript = "[^"]*cargo lipo[^"]*";')
    if pattern.search(project) is None:
        bail("generated Xcode project has no cargo lipo build phase to turn off")
    return pattern.sub(lambda _: 'shellScript = "true\\n";', project)


def rewrite(path: str, edit: list[tuple[str, str]], *, lipo: bool):
    file = Path(path)
    project = file.read_text(encoding="utf-8")
    for key, version in edit:
        project = set_deployment_target(project, key, version)
    if lipo:
        project = drop_lipo_phase(project)
    file.write_text(project, encoding="utf-8")


def set_version(plist: str, version: str):
    run(f'/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString {version}" {plist}')
