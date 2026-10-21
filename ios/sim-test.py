#!/usr/bin/env -S uv run -q --no-dev

# Runs the whole UI suite on an iOS simulator and exits with an error on any
# failure.
#
# The oldest iPhone this toolchain can boot is the iPhone 8 on iOS 16.4. Older
# devices cap at iOS 15, which no simulator runtime supports on this macOS, and
# the simulator renders on the host GPU, so an even older chip would prove
# nothing the render pipeline does not already show here.
#
# The app is x86_64 only for the simulator. The project excludes arm64 there, so
# it runs under Rosetta, and building the scheme instead falls back to Mac
# Catalyst arm64 and fails to link. So this builds the target against the
# iphonesimulator SDK directly with ARCHS=x86_64.
#
# Tests start through HILEN_RUN_TESTS, not the inspector. The app runs the suite
# on a worker task, prints a result marker and exits, so there is no mDNS to tell
# apart from the desktop lane running at the same time.
#
# On its own the suite streams live, so each test shows up as it runs and a hang
# names the test it stuck on. The app logs through NSLog, which tags every
# console line with a time and a process name, so the stream strips that prefix
# to read like the desktop runner.
#
# Under make ui this lane runs next to the desktop lanes, which would mangle 3
# streams into 1. That run sets HILEN_IOS_QUIET, and the lane goes back to
# buffering and prints only [ios] milestones. A failed command dumps its captured
# output either way.

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from shared.run import has, probe, run_quiet
from shared.util import bail, eprint, group, run_main

from shared import config, ios

if TYPE_CHECKING:
    from shared.config import Config

_DEVICE_NAME: Final = "te-iPhone8-16.4"
_DEVICE_TYPE: Final = "com.apple.CoreSimulator.SimDeviceType.iPhone-8"
_RUNTIME: Final = "com.apple.CoreSimulator.SimRuntime.iOS-16-4"
_RUNTIME_HINT: Final = "iOS 16.4"
_SHUTDOWN_WAIT_SECONDS: Final = 60

# The XCUITest of the mobile project that taps the screen and the keys of the
# screen keyboard for a test, see `system_input` in the engine. It listens on
# this port of the Mac, which the simulator shares.
_SYSTEM_INPUT_SCHEME: Final = "SystemInput"
_SYSTEM_INPUT_PORT: Final = 47815
_HARDWARE_KEYBOARD: Final = "com.apple.iphonesimulator ConnectHardwareKeyboard"

# far runs this lane on a build machine that many sessions share, see far.md in
# the comb repo. It gives each job an id and 100 ports of its own. With 1 device
# name and 1 port, 2 sessions at once would install into the same device and the
# second helper would not get the port.
_FAR_JOB: Final = "FAR_JOB"
_FAR_PORT: Final = "FAR_PORT"

# A cargo target folder of its own, so this build never blocks on the target lock
# of the desktop lane, which lets the 2 lanes truly run side by side. It sits
# under target, so the ignore of target already covers it.
_IOS_TARGET_DIR: Final = "target/ios"
_SIM_TRIPLE: Final = "x86_64-apple-ios"
_NSLOG_PREFIX: Final = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ \S+\[\d+:\d+\] ")
_RESULT: Final = re.compile(r"HILEN_TEST_RESULT (\d+) tests, (\d+) failed")
_DEVICE_ID: Final = re.compile(r"\(([0-9A-F-]{36})\)")


def _step(message: str):
    print(f"\n[ios] {message}", flush=True)


@dataclass(frozen=True, slots=True)
class _Lane:
    app: Config
    device_name: str
    port: int
    # A far job has no desktop session, so there is no Simulator app to open and
    # no hardware keyboard to take away. The device runs without a window.
    desktop: bool
    # The simulator spelling of the desktop `--human`. The app holds after every
    # check and every test until a tap on the screen.
    human: bool
    # Shows the 1 view HILEN_TEST_ONLY names full screen on the phone and keeps
    # the simulator up until ctrl-c.
    present: bool

    def xcodeproj(self) -> str:
        return f"mobile/iOS/{self.app.project_name}.xcodeproj"


# The output of a command, streamed live and kept, so the run stays watchable
# and the result marker can still be read from the text after. The NSLog prefix
# goes, the own stdout lines of the app, like the result marker, have none.
def _stream(command: str) -> str:
    output: list[str] = []
    with subprocess.Popen(
        ["sh", "-c", f"{command} 2>&1"], stdout=subprocess.PIPE, text=True, errors="replace"
    ) as child:
        if child.stdout is None:
            bail("no output stream")
        for raw in child.stdout:
            line = _NSLOG_PREFIX.sub("", raw.rstrip("\n"))
            print(line, flush=True)
            output.append(line)
    return "\n".join(output) + "\n"


# --lib only. The bin target fails to link on iOS, it needs a symbol the UIKit
# shell gives, and only the staticlib is wanted. Release, so the suite runs at
# real speed. The Xcode project links the lib from target/universal/release.
def _build_lib(lane: _Lane):
    lib = f"{_IOS_TARGET_DIR}/{_SIM_TRIPLE}/release/{lane.app.lib_name}"
    # No Rust toolchain here, the lib is built on a mac builder and comes back,
    # like in build-lib.py.
    local = has("cargo")
    if local:
        _step("adding the iOS simulator rust target")
        run_quiet(f"rustup target add {_SIM_TRIPLE}")
    _step("building the engine for iOS, this takes a while")
    build = (
        f"env CARGO_TARGET_DIR={_IOS_TARGET_DIR} IPHONEOS_DEPLOYMENT_TARGET=12.0 "
        f"cargo build -p {lane.app.app_name} --lib --target {_SIM_TRIPLE} --release"
    )
    if local:
        run_quiet(build)
    else:
        run_quiet(f"far --on mac 'rustup target add {_SIM_TRIPLE} && {build}'")
        run_quiet(f"far --on mac get {lib}")
    linked = f"target/universal/release/{lane.app.lib_name}"
    run_quiet(f"mkdir -p target/universal/release && cp {lib} {linked}")
    # The generated project is ignored by git, so it is made again only when it is
    # missing or older than the system input helper, not on every run.
    scheme = f"{lane.xcodeproj()}/xcshareddata/xcschemes/{_SYSTEM_INPUT_SCHEME}.xcscheme"
    if not Path(scheme).exists():
        if local:
            run_quiet("cargo install hilen-mobile --locked")
        run_quiet("hilen-mobile")


def _build_app(lane: _Lane) -> str:
    symroot = f"{Path.cwd()}/{_IOS_TARGET_DIR}/sim-build"
    _step("building the simulator app")
    run_quiet(
        f"xcodebuild -project {lane.xcodeproj()} -target {lane.app.project_name} "
        "-configuration Release -sdk iphonesimulator ARCHS=x86_64 VALID_ARCHS=x86_64 "
        f'ONLY_ACTIVE_ARCH=NO SYMROOT={symroot} OTHER_LDFLAGS="{ios.LDFLAGS}" build'
    )
    return f"{symroot}/Release-iphonesimulator/{lane.app.project_name}.app"


def _ensure_device(name: str) -> str:
    found = _DEVICE_ID.search(probe(f'xcrun simctl list devices | grep "{name} ("'))
    if found is not None:
        return group(found, 1)
    if _RUNTIME_HINT not in probe("xcrun simctl list runtimes"):
        bail(
            f"{_RUNTIME_HINT} simulator runtime is not installed, so the iPhone 8 device cannot "
            "be created. Install it before running the iOS test lane."
        )
    created = run_quiet(f'xcrun simctl create "{name}" {_DEVICE_TYPE} {_RUNTIME}').strip()
    if not created:
        bail("Failed to create the simulator device")
    return created


def _boot_device(device: str, name: str):
    for elapsed in range(_SHUTDOWN_WAIT_SECONDS):
        if "(Shutting Down)" not in probe(f'xcrun simctl list devices | grep "{name} ("'):
            run_quiet(f"xcrun simctl bootstatus {device} -b")
            return
        if elapsed == 0:
            _step(f"waiting for {name} to finish shutting down")
        time.sleep(1)
    bail(f"{name} did not finish shutting down within {_SHUTDOWN_WAIT_SECONDS} seconds")


def _launch_line(lane: _Lane, device: str) -> str:
    # simctl passes only SIMCTL_CHILD_ prefixed variables into the app, so the
    # narrowing list and the human flag go under that prefix.
    env = ["SIMCTL_CHILD_HILEN_PRESENT=1" if lane.present else "SIMCTL_CHILD_HILEN_RUN_TESTS=1"]
    only = os.environ.get("HILEN_TEST_ONLY")
    if only is not None:
        env.append(f'SIMCTL_CHILD_HILEN_TEST_ONLY="{only}"')
    if lane.human:
        env.append("SIMCTL_CHILD_HILEN_HUMAN=1")
    env.append(f"SIMCTL_CHILD_HILEN_SYSTEM_INPUT=127.0.0.1:{lane.port}")
    return (
        f"{' '.join(env)} xcrun simctl launch --console --terminate-running-process {device} "
        f"{lane.app.bundle_id}"
    )


# The setting is read when Simulator starts, so it is put back after the run.
def _restore_keyboard(saved: str):
    match saved.strip():
        case "0":
            pass
        case "1":
            run_quiet(f"defaults write {_HARDWARE_KEYBOARD} -bool true")
        # It was never set, which reads as an error text.
        case _:
            run_quiet(f"defaults delete {_HARDWARE_KEYBOARD}")


def _run_suite(lane: _Lane, device: str, app_path: str) -> str:
    helper_data = f"{Path.cwd()}/{_IOS_TARGET_DIR}/system-input"
    helper_build = (
        f"-project {lane.xcodeproj()} -scheme {_SYSTEM_INPUT_SCHEME} "
        f'-destination "platform=iOS Simulator,id={device}" -derivedDataPath {helper_data}'
    )
    _step("building the system input helper")
    run_quiet(f"xcodebuild build-for-testing {helper_build}")
    # With a hardware keyboard connected the simulator shows no screen keyboard,
    # and the keyboard tests have no keys to tap.
    saved_keyboard = probe(f"defaults read {_HARDWARE_KEYBOARD}")
    if lane.desktop:
        probe("osascript -e 'tell application \"Simulator\" to quit'")
        run_quiet(f"defaults write {_HARDWARE_KEYBOARD} -bool false")
    _step(f"booting {lane.device_name}")
    _boot_device(device, lane.device_name)
    if lane.desktop:
        run_quiet("open -a Simulator")
    run_quiet(f'xcrun simctl install {device} "{app_path}"')

    # HILEN_RUN_TESTS makes the app run the suite and exit. --console streams its
    # stdout here, so the result marker arrives before the launch returns.
    _step("running the UI suite on the simulator")
    helper_log = f"{_IOS_TARGET_DIR}/system-input.log"
    helper = subprocess.Popen(
        [
            "sh",
            "-c",
            (
                f"TEST_RUNNER_HILEN_BUNDLE_ID={lane.app.bundle_id} "
                f"TEST_RUNNER_HILEN_SYSTEM_INPUT_PORT={lane.port} exec "
                f"xcodebuild test-without-building {helper_build} > {helper_log} 2>&1"
            ),
        ]
    )
    launch = _launch_line(lane, device)
    # Under make ui 3 lanes run at once, so this lane stays quiet. On its own it
    # streams every test live. A human run always streams, it holds for the user
    # and the prompts are the only sign of where it stands.
    quiet = "HILEN_IOS_QUIET" in os.environ and not lane.human and not lane.present
    output = probe(f"{launch} 2>&1") if quiet else _stream(launch)
    # The helper serves until it is stopped, the app is its only client.
    helper.kill()
    helper.wait()

    run_quiet(f"xcrun simctl shutdown {device} || true")
    if lane.desktop:
        probe("osascript -e 'tell application \"Simulator\" to quit'")
        _restore_keyboard(saved_keyboard)
    else:
        # The device has the name of this job, no later run finds it again.
        run_quiet(f"xcrun simctl delete {device}")
    return output


def main() -> int:
    if sys.platform != "darwin":
        print("[ios] not macOS, skipping the iOS simulator lane.")
        return 0
    job = os.environ.get(_FAR_JOB)
    args = sys.argv[1:]
    lane = _Lane(
        app=config.read(),
        device_name=_DEVICE_NAME if job is None else f"{_DEVICE_NAME}-{job}",
        port=int(os.environ.get(_FAR_PORT, str(_SYSTEM_INPUT_PORT))),
        desktop=job is None,
        human="--human" in args,
        present="--present" in args,
    )
    if lane.present and "HILEN_TEST_ONLY" not in os.environ:
        bail("[ios] --present needs HILEN_TEST_ONLY naming exactly one test")
    _build_lib(lane)
    app_path = _build_app(lane)
    device = _ensure_device(lane.device_name)
    output = _run_suite(lane, device, app_path)
    if lane.present:
        return 0
    found = _RESULT.search(output)
    if found is None:
        eprint(output)
        bail("[ios] sim run produced no result marker. See the launch output above.")
    total, failed = int(found[1]), int(found[2])
    if failed != 0:
        eprint(output)
        _step(f"FAILED: {total} tests, {failed} failed")
        return 1
    _step(f"ok: {total} tests, 0 failed")
    return 0


if __name__ == "__main__":
    run_main(main)
