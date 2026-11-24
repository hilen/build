# 1 app in the iOS simulator of this Mac that an agent drives with real
# touches and the real screen keyboard, `make sim`. The Simulator window stays
# open, so a person sees every step. See ios-debug.md of the hilen skill.
#
# The app, its Xcode project and the system input helper, an XCUITest of that
# project, are built on a mac builder through far and come back. This Mac only
# boots, installs and starts. The helper takes 1 request per line on a local
# port and answers once the action is done, see SystemInput.swift in the
# template of hilen-mobile.
#
# Every command returns, so a person and an agent use it the same way. What
# runs is kept in a file between the commands.

import contextlib
import enum
import os
import re
import shlex
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

import msgspec

from shared import config, ios
from shared.hot import inspect_tool, is_alive
from shared.make_device import engine_repo
from shared.run import capture, probe, run, run_allow_fail, run_quiet
from shared.util import ScriptError, bail, group

if TYPE_CHECKING:
    from shared.config import Config

_DIR: Final = "target/ios/sim"
_STATE: Final = "state.json"
_APP_LOG: Final = "app.log"
_HELPER_LOG: Final = "helper.log"
_SHOTS: Final = "shots"
_TRIPLE: Final = "aarch64-apple-ios-sim"
# No arm64 simulator is older than iOS 14.
_MINIMUM: Final = "14.0"
# The generated project leaves arm64 out of a simulator build, see sim-test.py.
_ARCH: Final = "ARCHS=arm64 EXCLUDED_ARCHS="
_SCHEME: Final = "SystemInput"
# Not the 47815 of the UI test lane, so a session and `make ui-ios` do not meet.
_PORT: Final = 47816
_HARDWARE_KEYBOARD: Final = "com.apple.iphonesimulator ConnectHardwareKeyboard"
_KEYBOARD_VALUES: Final = ("0", "1")
# A fresh device covers its first keyboard with a card about typing by sliding
# a finger, and the keys under it take no tap.
_SLIDE_TYPING_SEEN: Final = (
    "defaults write com.apple.keyboard.preferences DidShowContinuousPathIntroduction -bool true"
)
# Built from main on the builder, like mobile.py does, cargo builds it again only
# when main moved.
_GENERATOR: Final = (
    "cargo install --git https://github.com/hilen/hilen-mobile --branch main --locked "
    "hilen-mobile --root target/hilen-mobile"
)
# A GitHub mac took 98 s from the install to a serving helper.
_HELPER_SECONDS: Final = 300
_APP_SECONDS: Final = 60
# The helper waits up to 10 s for the keyboard before each key, so a long text
# takes long.
_REPLY_SECONDS: Final = 300
_BOOTED: Final = "Booted"
_INSPECT_PORT: Final = re.compile(r"Inspect server on port: (\d+)")
# A line of `hilen-inspect find`: label and text, then `[x, y] WxH  status  id`.
_FIND_LINE: Final = re.compile(r"\[(-?[\d.]+), (-?[\d.]+)\] ([\d.]+)x([\d.]+)  visible  \S*$")
# A line of `hilen-inspect windows` for the main window: `0  WxH  title`.
_WINDOW_LINE: Final = re.compile(r"^0\s+([\d.]+)x([\d.]+)", re.MULTILINE)
_ESCAPED: Final = re.compile(r"\\(.)")
# A real UIPageViewController to compare the engine with, in the engine repo.
_REFERENCE_SOURCE: Final = "uikit-reference"
_REFERENCE_APP: Final = "target/uikit-reference/UIKitReference.app"
_REFERENCE_ID: Final = "hilen.uikit-reference"
_REFERENCE_LOG: Final = "reference.log"
_REFERENCE_MINIMUM: Final = "16.0"


class Phone(enum.Enum):
    IPHONE_17_PRO = "iPhone-17-Pro"
    IPHONE_8 = "iPhone-8"

    def runtime(self) -> str:
        match self:
            case Phone.IPHONE_17_PRO:
                return "iOS-26-3"
            case Phone.IPHONE_8:
                return "iOS-16-4"

    def device_name(self) -> str:
        return f"hilen-sim-{self.value}"


class _Device(msgspec.Struct, frozen=True):
    udid: str
    name: str
    state: str


class _Devices(msgspec.Struct, frozen=True):
    devices: dict[str, tuple[_Device, ...]]


class _State(msgspec.Struct, frozen=True):
    device: str
    bundle_id: str
    # Process groups of this Mac: the helper and the console of the app.
    helper: int
    console: int
    # Where hilen-inspect reaches the app, the simulator shares the network of
    # this Mac.
    inspect: str
    # ConnectHardwareKeyboard of the Simulator before the session, empty when
    # it was never set.
    keyboard: str
    phone: str
    # The second device next to the first, for a person to compare, empty
    # while there is none.
    beside: str = ""
    # The test run of the helper, to start it again after XCTest ended it.
    xctestrun: str = ""


def start(root: Path, phone: Phone, template: Path | None):
    if _read_state(root) is not None:
        bail("a session runs here, `make sim args=stop` ends it")
    if _serves():
        bail(f"port {_PORT} is taken, a helper of another session still runs")
    app = config.read()
    folder = root / _DIR
    for old in (folder / _SHOTS).glob("*.png"):
        old.unlink()
    app_path, products = _build(app, root, template)
    xctestrun = next(products.glob("*.xctestrun"), None)
    if xctestrun is None:
        bail(f"the helper build left no .xctestrun in {products}")
    tool = inspect_tool(engine_repo(root))

    device = _device(phone)
    keyboard = probe(f"defaults read {_HARDWARE_KEYBOARD}").strip()
    if keyboard not in _KEYBOARD_VALUES:
        keyboard = ""
    # The Simulator reads the setting when it starts. With a hardware keyboard
    # it shows no screen keyboard.
    if keyboard != "0":
        run_allow_fail("osascript -e 'tell application \"Simulator\" to quit'")
        run(f"defaults write {_HARDWARE_KEYBOARD} -bool false")
    if device.state != _BOOTED:
        run(f"xcrun simctl boot {device.udid}")
    run_quiet(f"xcrun simctl bootstatus {device.udid} -b")
    run(f"xcrun simctl spawn {device.udid} {_SLIDE_TYPING_SEEN}")
    run(
        'open -a "$(xcode-select -p)/Applications/Simulator.app" '
        f"--args -CurrentDeviceUDID {device.udid}"
    )
    run(f"xcrun simctl install {device.udid} {shlex.quote(str(app_path))}")

    # The runner of the helper is an app too, and the one that comes up last is
    # in front, so the app starts only once the helper serves.
    helper = _start_helper(xctestrun, device.udid, app.bundle_id, folder / _HELPER_LOG)
    console = _launch(device.udid, app.bundle_id, folder / _APP_LOG)
    inspect = _wait_for_inspect(folder / _APP_LOG, console)
    state = _State(
        device.udid,
        app.bundle_id,
        helper,
        console,
        inspect,
        keyboard,
        phone.value,
        "",
        str(xctestrun),
    )
    (folder / _STATE).write_bytes(msgspec.json.encode(state))

    print(f"\nsession up: {app.project_name} on {device.name} {device.udid}")
    print(f"  app log     {folder / _APP_LOG}")
    print(f"  helper log  {folder / _HELPER_LOG}")
    print(f"  inspector   {tool} --addr '{inspect}' tree")


def stop(root: Path):
    state = _session(root)
    run_allow_fail(f"xcrun simctl terminate {state.device} {state.bundle_id}")
    _end_group(state.helper)
    _end_group(state.console)
    run_allow_fail(f"xcrun simctl shutdown {state.device}")
    if state.beside:
        run_allow_fail(f"xcrun simctl shutdown {state.beside}")
    match state.keyboard:
        case "0":
            pass
        case "1":
            run(f"defaults write {_HARDWARE_KEYBOARD} -bool true")
        case _:
            run(f"defaults delete {_HARDWARE_KEYBOARD}")
    (root / _DIR / _STATE).unlink()
    print("session stopped")


# The real UIPageViewController of the engine repo, on the device of the
# session where the helper drives it, or `beside` it on a second device for a
# person. With `measure` it prints its touches and every move of its pages.
def reference(root: Path, *, beside: bool, measure: bool) -> Path:
    state = _session(root)
    engine = engine_repo(root)
    source = _REFERENCE_SOURCE
    app = _REFERENCE_APP
    line = " && ".join(
        (
            f"rm -rf {app} && mkdir -p {app}",
            f"cp {source}/Info.plist {app}/",
            (
                "xcrun -sdk iphonesimulator swiftc -swift-version 5 -parse-as-library -O "
                f"-target arm64-apple-ios{_REFERENCE_MINIMUM}-simulator "
                f"{source}/PageReference.swift -o {app}/UIKitReference"
            ),
            f"codesign -s - --force {app}",
        )
    )
    folder = shlex.quote(str(engine))
    run(f"cd {folder} && far --on mac {shlex.quote(line)}")
    run(f"cd {folder} && far --on mac get {app}")
    device = state.device
    if beside:
        device = _beside(root, state)
    run(f"xcrun simctl install {device} {shlex.quote(str(engine / app))}")
    log = root / _DIR / _REFERENCE_LOG
    flag = "SIMCTL_CHILD_HILEN_MEASURE=1 " if measure else ""
    _detached(
        f"{flag}exec xcrun simctl launch --console-pty --terminate-running-process "
        f"{device} {_REFERENCE_ID} > {shlex.quote(str(log))} 2>&1"
    )
    return log


def _beside(root: Path, state: _State) -> str:
    phone = Phone(state.phone)
    device = _device_named(f"{phone.device_name()}-beside", phone)
    if device.state != _BOOTED:
        run(f"xcrun simctl boot {device.udid}")
    run_quiet(f"xcrun simctl bootstatus {device.udid} -b")
    beside = msgspec.structs.replace(state, beside=device.udid)
    (root / _DIR / _STATE).write_bytes(msgspec.json.encode(beside))
    return device.udid


# 1 request to the helper, its answer with the `ok` taken off.
def ask(root: Path, request: str) -> str:
    state = _session(root)
    reply = _send(request)
    if not is_alive(state.helper) and state.xctestrun:
        # XCTest ends the whole test on 1 failed screen query, like a query
        # that timed out while an app came to the front, seen on 2026-11-24.
        # The helper starts again and the request goes once more.
        print("the system input helper ended, it starts again", flush=True)
        log = root / _DIR / _HELPER_LOG
        helper = _start_helper(Path(state.xctestrun), state.device, state.bundle_id, log)
        state = msgspec.structs.replace(state, helper=helper)
        (root / _DIR / _STATE).write_bytes(msgspec.json.encode(state))
        reply = _send(request)
    word, _, rest = reply.partition(" ")
    if word == "ok":
        return rest
    log = root / _DIR / _HELPER_LOG
    msg = f"{request}: {reply or f'no answer, see {log}'}"
    raise ScriptError(msg)


def _send(request: str) -> str:
    try:
        with socket.create_connection(("127.0.0.1", _PORT), timeout=_REPLY_SECONDS) as link:
            link.sendall(f"{request}\n".encode())
            return _read_line(link)
    except OSError as err:
        return f"error {err}"


# A picture of the whole screen with the keyboard and the system views, which a
# screenshot of the inspector does not hold.
def shot(root: Path, path: Path | None) -> Path:
    state = _session(root)
    if path is None:
        shots = root / _DIR / _SHOTS
        shots.mkdir(parents=True, exist_ok=True)
        path = shots / f"{len(list(shots.glob('*.png'))) + 1:03}.png"
    run_quiet(f"xcrun simctl io {state.device} screenshot {shlex.quote(str(path))}")
    return path.resolve()


# The middle of the 1 visible engine view that `query` finds, in screen points.
def view_point(root: Path, query: str) -> tuple[float, float]:
    state = _session(root)
    tool = inspect_tool(engine_repo(root))
    found = capture(f"{tool} --addr '{state.inspect}' find {shlex.quote(query)}")
    windows = capture(f"{tool} --addr '{state.inspect}' windows")
    screen_width = float(ask(root, "screen").split()[0])
    return find_point(found, screen_width / window_width(windows))


def find_point(found: str, ratio: float) -> tuple[float, float]:
    lines = [line for line in found.splitlines() if line.strip()]
    matches = [m for m in map(_FIND_LINE.search, lines) if m is not None]
    if len(matches) != 1:
        listed = "\n".join(lines)
        bail(f"{len(lines)} visible views match, the query must find 1:\n{listed}")
    x, y, width, height = (float(group(matches[0], n)) for n in range(1, 5))
    return (x + width / 2) * ratio, (y + height / 2) * ratio


def window_width(windows: str) -> float:
    found = _WINDOW_LINE.search(windows)
    if found is None:
        bail(f"no main window in:\n{windows}")
    return float(group(found, 1))


# The helper sends a dump on 1 line, a line end as `\n` and a backslash as `\\`.
def unescape(text: str) -> str:
    return _ESCAPED.sub(_unescaped, text)


def _unescaped(found: re.Match[str]) -> str:
    char = group(found, 1)
    return "\n" if char == "n" else char


def _build(app: Config, root: Path, template: Path | None) -> tuple[Path, Path]:
    out = f"{_DIR}/build"
    lib = f"target/ios/{_TRIPLE}/release/{app.lib_name}"
    project = f"mobile/iOS/{app.project_name}.xcodeproj"
    generate = "./target/hilen-mobile/bin/hilen-mobile"
    if template is not None:
        _send_repo_of(template)
        # far keeps the folders as they lie here, so the same relative path is
        # right on the builder.
        generate += f" --path {shlex.quote(os.path.relpath(template, root))}"
    steps = (
        f"rustup target add {_TRIPLE}",
        (
            f"env CARGO_TARGET_DIR=target/ios IPHONEOS_DEPLOYMENT_TARGET={_MINIMUM} cargo build "
            f"-p {app.app_name} --lib --target {_TRIPLE} --release --features hilen/inspect"
        ),
        f"mkdir -p target/universal/release && cp {lib} target/universal/release/",
        _GENERATOR,
        generate,
        (
            f"xcodebuild -project {project} -target {app.project_name} -configuration Release "
            f"-sdk iphonesimulator {_ARCH} IPHONEOS_DEPLOYMENT_TARGET={_MINIMUM} "
            f'ONLY_ACTIVE_ARCH=NO SYMROOT="$PWD/{out}/app" OTHER_LDFLAGS="{ios.LDFLAGS}" build'
        ),
        (
            f"xcodebuild build-for-testing -project {project} -scheme {_SCHEME} "
            f"-destination 'generic/platform=iOS Simulator' -derivedDataPath {out}/helper {_ARCH}"
        ),
    )
    run(f"far --on mac {shlex.quote(' && '.join(steps))}")
    app_path = f"{out}/app/Release-iphonesimulator/{app.project_name}.app"
    products = f"{out}/helper/Build/Products"
    run(f"far --on mac get {app_path}")
    run(f"far --on mac get {products}")
    return root / app_path, root / products


def _send_repo_of(folder: Path):
    repo = capture(f"git -C {shlex.quote(str(folder))} rev-parse --show-toplevel")
    run(f"cd {shlex.quote(repo)} && far --on mac true")


def _device(phone: Phone) -> _Device:
    return _device_named(phone.device_name(), phone)


def _device_named(name: str, phone: Phone) -> _Device:
    listed = msgspec.json.decode(capture("xcrun simctl list -j devices"), type=_Devices)
    for devices in listed.devices.values():
        for device in devices:
            if device.name == name:
                return device
    udid = capture(
        f"xcrun simctl create {name} com.apple.CoreSimulator.SimDeviceType.{phone.value} "
        f"com.apple.CoreSimulator.SimRuntime.{phone.runtime()}"
    )
    return _Device(udid=udid, name=name, state="Shutdown")


def _start_helper(xctestrun: Path, device: str, bundle_id: str, log: Path) -> int:
    line = (
        f"TEST_RUNNER_HILEN_BUNDLE_ID={bundle_id} TEST_RUNNER_HILEN_SYSTEM_INPUT_PORT={_PORT} "
        f"exec xcodebuild test-without-building -xctestrun {shlex.quote(str(xctestrun))} "
        f"-destination id={device} > {shlex.quote(str(log))} 2>&1"
    )
    print("starting the system input helper", flush=True)
    child = _detached(line)
    end = time.monotonic() + _HELPER_SECONDS
    while time.monotonic() < end:
        if child.poll() is not None:
            bail(f"the system input helper ended before it served, see {log}")
        if _serves():
            return child.pid
        time.sleep(1)
    _end_group(child.pid)
    msg = f"the system input helper did not serve in {_HELPER_SECONDS} s, see {log}"
    raise ScriptError(msg)


def _launch(device: str, bundle_id: str, log: Path) -> int:
    log.unlink(missing_ok=True)
    # A release build starts the inspect server only with HILEN_INSPECT, and
    # simctl passes only SIMCTL_CHILD_ variables into the app.
    line = (
        f"SIMCTL_CHILD_HILEN_INSPECT=1 exec xcrun simctl launch --console-pty "
        f"--terminate-running-process {device} {bundle_id} > {shlex.quote(str(log))} 2>&1"
    )
    print(f"starting {bundle_id}", flush=True)
    return _detached(line).pid


# A process that outlives this command, in a group of its own, so `stop` ends
# it with everything it started.
def _detached(line: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(["sh", "-c", line], stdin=subprocess.DEVNULL, start_new_session=True)


def _wait_for_inspect(log: Path, console: int) -> str:
    end = time.monotonic() + _APP_SECONDS
    while time.monotonic() < end:
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        found = _INSPECT_PORT.search(text)
        if found is not None:
            return f"[::1]:{group(found, 1)}"
        if not is_alive(console):
            bail(f"the app ended before its inspect server was up, see {log}")
        time.sleep(0.5)
    msg = f"the app wrote no inspect port in {_APP_SECONDS} s, see {log}"
    raise ScriptError(msg)


def _serves() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _PORT), timeout=1):
            return True
    except OSError:
        return False


def _read_line(link: socket.socket) -> str:
    data = b""
    while not data.endswith(b"\n"):
        chunk = link.recv(65536)
        if not chunk:
            break
        data += chunk
    return data.decode(errors="replace").rstrip("\n")


def _end_group(pid: int):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGTERM)


def _read_state(root: Path) -> _State | None:
    try:
        return msgspec.json.decode((root / _DIR / _STATE).read_bytes(), type=_State)
    except FileNotFoundError:
        return None


def _session(root: Path) -> _State:
    state = _read_state(root)
    if state is None:
        bail("no session runs here, `make sim args=start` starts one")
    return state
