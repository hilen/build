# What the iOS and the tvOS project builds share: hilen-mobile makes the Xcode
# project, then the settings of the app go over the ones of its template.

import os
import re
from collections.abc import Sequence
from pathlib import Path

from shared.run import has, run
from shared.util import bail


def generate(args: Sequence[str]):
    os.environ.pop("CFLAGS", None)
    os.environ.pop("CXXFLAGS", None)
    if has("cargo"):
        run("cargo install hilen-mobile --locked")
    elif not has("hilen-mobile"):
        # A machine with no Rust toolchain gets the generator ready built.
        bail("hilen-mobile is not installed and this machine has no cargo to install it")
    run(f"hilen-mobile {' '.join(args)}".strip())


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
