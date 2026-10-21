# Hot reload of an app in the iOS simulator or in the Apple TV simulator, see
# docs/hot-reload.md in hilen.
#
# The app is built as 1 dynamic library. A small loader app is installed once
# and loads the library from a folder on this Mac. Every new build lands in that
# folder under a new name, and the loader swaps to it while the app keeps
# running.
#
# The simulator runs on the Mac the script starts on. The builds run through
# `far` when it is there, on a build machine, and here otherwise.

import dataclasses
import os
import shutil
import tempfile
import time
import tomllib
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self

import msgspec

from shared import tvos
from shared.run import capture, probe, run, run_allow_fail, run_quiet
from shared.util import ScriptError, bail

if TYPE_CHECKING:
    from shared.config import Config

# The simulator of an Apple Silicon Mac. No Rosetta, which keeps a translation
# of every library a process ever loaded.
_TARGET: Final = "aarch64-apple-ios-sim"
# A real iPhone, see "A real iPhone" in docs/hot-reload.md.
_DEVICE_TARGET: Final = "aarch64-apple-ios"
# Where Xcode keeps the provisioning profiles it made.
_PROFILES: Final = "Library/Developer/Xcode/UserData/Provisioning Profiles"
# No arm64 simulator is older than iOS 14.
_IOS_MINIMUM: Final = "14.0"
# The oldest tvOS of a normal build, see docs/tvos.md in hilen.
_TVOS_MINIMUM: Final = "15.0"
# tvOS has no prebuilt standard library, a build compiles it too.
_TVOS_BUILD_STD: Final = " -Z build-std=std,panic_abort"
# The word of a command line that asks for an Apple TV.
_TV_WORD: Final = "tv"
# The flag takes rayon out of the engine, its threads never end.
_HOT_CFG: Final = '["--cfg","hilen_hot"]'
# The folder of the libraries and the pointer file, below the repo root.
_HOT_DIR: Final = "target/hot/lib"
_POINTER: Final = "current"
# The loader writes the name of the library it started into this file.
_STARTED: Final = "started"
# The source an app takes the engine from. A library that must carry the engine
# of a folder on disk is built with this source pointed there.
_ENGINE_GIT: Final = "https://github.com/hilen/hilen.git"
# The lock file of an app is put aside here while the engine of a folder is
# built in, so the build leaves the repo of the app as it was.
_KEPT_LOCK: Final = "target/hot-Cargo.lock"
_STARTED_TRIES: Final = 240
# The running app has the newest library mapped and loads the next one before
# it lets go, so 2 files are in use at most.
_LIBRARIES_KEPT: Final = 3
# Set inside a far job, see far.md in the comb repo.
_FAR_JOB: Final = "FAR_JOB"
# The device of a far job, the same one the UI test lane makes.
_JOB_DEVICE_TYPE: Final = "com.apple.CoreSimulator.SimDeviceType.iPhone-8"
_JOB_RUNTIME: Final = "com.apple.CoreSimulator.SimRuntime.iOS-16-4"
# The Apple TV of a far job, the one docs/tvos.md in hilen was proven on.
_JOB_TV_DEVICE_TYPE: Final = (
    "com.apple.CoreSimulator.SimDeviceType.Apple-TV-4K-3rd-generation-1080p"
)
_JOB_TV_RUNTIME: Final = "com.apple.CoreSimulator.SimRuntime.tvOS-26-2"
# A `simctl` list has the devices of a system under a line like
# `-- tvOS 26.2 --`.
_SECTION: Final = "-- "
_TV_SECTION: Final = "tvOS"
# A TV picture of this size draws 4 times fewer pixels than 4K.
_TV_SMALL: Final = "1080p"
_MARKER_POLL: Final = 0.25
_MARKER_TRIES: Final = 120
# Folders a change in which is no change of the app.
_NOT_WATCHED: Final = frozenset({"target", "build", "mobile", "dist", "node_modules", "bench"})
_ID_LENGTH: Final = 36
_ID_DASHES: Final = 4
_KIB: Final = 1024
_BMP_FIELD: Final = 4
_BMP_PIXEL: Final = 3
# The hash is the 2nd word of an identity line.
_HASH_AT: Final = 1


class _Package(msgspec.Struct, frozen=True):
    name: str
    manifest_path: str


class _Metadata(msgspec.Struct, frozen=True):
    packages: tuple[_Package, ...] = ()


# The system a hot library and its loader are built for.
class System(Enum):
    IOS = auto()
    TVOS = auto()

    # Takes the word that asks for an Apple TV off the front of `args`.
    @staticmethod
    def take(args: list[str]) -> System:
        if args and args[0] == _TV_WORD:
            del args[0]
            return System.TVOS
        return System.IOS


@dataclass(frozen=True, slots=True)
class _Loader:
    sdk: str
    clang_target: str
    plist: str


@dataclass(frozen=True, slots=True)
class Hot:
    system: System
    # The builds go to a build machine.
    far: bool
    root: Path
    # The name of the loader app and of its executable.
    executable: str
    bundle_id: str
    # The folder of the libraries and the pointer file.
    dir: Path
    # The repo of an engine on disk the library is built with, in place of the
    # engine the app names.
    engine: Path | None = None
    # The library is for a real iPhone, not for the simulator.
    device: bool = False

    @classmethod
    def new(cls, config: Config) -> Self:
        return cls.named(config.project_name, f"{config.bundle_id}.hot")

    # `bundle_id` is a name of its own, so the loader does not replace the normal
    # app in the simulator.
    @classmethod
    def named(cls, executable: str, bundle_id: str) -> Self:
        return cls.at(Path.cwd(), executable, bundle_id)

    # Like `named`, for the repo at `root` in place of the current folder.
    @classmethod
    def at(cls, root: Path, executable: str, bundle_id: str) -> Self:
        # Inside a far job this machine is the builder already.
        on_builder = _FAR_JOB in os.environ
        return cls(
            system=System.IOS,
            far=not on_builder and bool(probe("command -v far").strip()),
            root=root,
            executable=executable,
            bundle_id=bundle_id,
            dir=root / _HOT_DIR,
        )

    # The library is built for a real iPhone.
    def for_device(self) -> Self:
        return dataclasses.replace(self, device=True)

    # The library and the loader are built for `system`. An Apple TV gets folders
    # of its own, so a loader of 1 system never sees a library of the other. Call
    # it before `with_dir`.
    def for_system(self, system: System) -> Self:
        changed = dataclasses.replace(self, system=system)
        return dataclasses.replace(changed, dir=self.root / changed.out() / "lib")

    # The folder of everything a hot build makes, below the repo root.
    def out(self) -> str:
        return "target/hot" if self.system is System.IOS else "target/hot/tv"

    def target(self) -> str:
        match self.system, self.device:
            case System.IOS, False:
                return _TARGET
            case System.IOS, True:
                return _DEVICE_TARGET
            case System.TVOS, False:
                return tvos.SIMULATOR
            case System.TVOS, True:
                return tvos.DEVICE

    # What the loader is compiled with, for the simulator or a real device: the
    # SDK, the target of `clang` and the file the `Info.plist` is made from.
    def _loader(self, *, device: bool) -> _Loader:
        simulator = "" if device else "-simulator"
        if self.system is System.IOS:
            sdk = "iphoneos" if device else "iphonesimulator"
            return _Loader(sdk, f"arm64-apple-ios{_IOS_MINIMUM}{simulator}", "hot_loader.plist")
        sdk = "appletvos" if device else "appletvsimulator"
        return _Loader(sdk, f"arm64-apple-tvos{_TVOS_MINIMUM}{simulator}", "hot_loader_tvos.plist")

    # The cargo argument that adds the hot flag to the compiler flags. Cargo
    # takes the flags of a target and then ignores the general ones, so the flag
    # goes where the repo keeps its own.
    def _hot_flag(self) -> str:
        target = self.target()
        try:
            parsed = tomllib.loads((self.root / ".cargo/config.toml").read_text(encoding="utf-8"))
        except OSError, tomllib.TOMLDecodeError:
            parsed = {}
        targets = parsed.get("target")
        flags = targets.get(target) if isinstance(targets, dict) else None
        if isinstance(flags, dict) and "rustflags" in flags:
            return f"--config 'target.{target}.rustflags={_HOT_CFG}'"
        return f"--config 'build.rustflags={_HOT_CFG}'"

    # Another folder for the libraries, below the repo root.
    def with_dir(self, folder: str) -> Self:
        return dataclasses.replace(self, dir=self.root / folder)

    # The library is built with the engine of the repo at `engine`.
    def with_engine(self, engine: Path) -> Self:
        return dataclasses.replace(self, engine=engine)

    # A shell line in the repo, on this machine.
    def _in_root(self, line: str) -> str:
        return f'cd "{self.root}" && {line}'

    # A shell line in the repo, on the machine that builds.
    def _on_builder(self, line: str) -> str:
        if self.far:
            quoted = line.replace("'", "'\\''")
            return self._in_root(f"far '{quoted}'")
        return self._in_root(line)

    def _fetch(self, path: str):
        if self.far:
            run(self._in_root(f"far get {path}"))

    # The builder gets the engine folder as it is here now. A job of the app
    # sends only the repo of the app.
    def _send_engine(self):
        if self.engine is not None and self.far:
            run(f'cd "{self.engine}" && far true')

    # What the toolchain of the builder needs for the build. It is a part of the
    # build line, as a job of its own it cost every build about a second on a
    # machine that builds through far.
    def _prepare(self) -> str:
        if self.system is System.IOS:
            return f"rustup target add {self.target()}"
        # A tvOS target can't be added, it is built from the sources.
        return "rustup component add rust-src"

    # Builds `package` as 1 dynamic library with the engine inside and brings it
    # here. `features` are more cargo features of the package. It is a release
    # build, a debug build of an app drew a frame several times slower and made a
    # phone hot.
    def build_library(self, package: str, features: str) -> Path:
        if self.system is System.IOS:
            minimum, build_std = f"IPHONEOS_DEPLOYMENT_TARGET={_IOS_MINIMUM}", ""
        else:
            minimum, build_std = f"TVOS_DEPLOYMENT_TARGET={_TVOS_MINIMUM}", _TVOS_BUILD_STD
        exports = f"export CFLAGS= SDKROOT= {minimum}"
        target = self.target()
        cargo = (
            f"cargo rustc -p {package} --lib --release --target {target} --crate-type cdylib "
            f"--features hilen/hot{features} {self._hot_flag()}{build_std}"
        )
        if self.engine is None:
            line = f"{exports}; {cargo}"
        else:
            # The same relative path is right on the builder, far keeps the
            # folders as they lie here.
            path = os.path.relpath(self.engine / "hilen", self.root)
            patch = f'--config \'patch."{_ENGINE_GIT}".hilen.path="{path}"\''
            # The new source of the engine changes the lock file.
            keep = f"mkdir -p target && cp Cargo.lock {_KEPT_LOCK}"
            restore = f"status=$?; cp {_KEPT_LOCK} Cargo.lock; exit $status"
            line = f"{exports}; {keep} && {cargo} {patch}; {restore}"
        self._send_engine()
        run(self._on_builder(f"{self._prepare()} || exit 1; {line}"))
        library = f"target/{target}/release/lib{package.replace('-', '_')}.dylib"
        self._fetch(library)
        return self.root / library

    # Builds the loader app on the builder, from the 2 files of the engine crate,
    # and brings it here.
    def build_loader(self) -> Path:
        native = self._native_dir()
        app = f"{self.out()}/{self.executable}.app"
        loader = self._loader(device=False)
        line = (
            f"rm -rf {app} && mkdir -p {app} && "
            f"sed -e s/HILEN_EXECUTABLE/{self.executable}/g "
            f"-e s/HILEN_BUNDLE_ID/{self.bundle_id}/g "
            f"{native}/{loader.plist} > {app}/Info.plist && "
            f"if [ -d assets ]; then cp -R assets {app}/assets; fi && "
            f"xcrun -sdk {loader.sdk} clang -target {loader.clang_target} -fobjc-arc -Wall "
            f"{native}/hot_loader.m -framework UIKit -framework Foundation "
            f"-o {app}/{self.executable} && codesign -s - --force {app}"
        )
        run(self._on_builder(line))
        self._fetch(app)
        return self.root / app

    # Builds a program of this repo that has to run on this Mac and brings it
    # here.
    def build_tool(self, package: str, program: str):
        run(self._on_builder(f"cargo build -p {package}"))
        self._fetch(program)

    # Builds the loader app for a real iPhone or Apple TV, here and not on a
    # builder, since the development certificate is on this Mac. `library` is
    # the app the loader shows when nothing was sent to it, it goes into the
    # loader app. Run from the hilen repo, the loader source is taken from this
    # folder.
    def build_device_loader(self, library: Path) -> Path:
        native = "hilen/native/ios"
        folder = f"{self.out()}/device"
        app = f"{folder}/{self.executable}.app"
        loader = self._loader(device=True)
        profile = development_profile(self.bundle_id, self.system)
        identity = sign_identity()
        line = (
            f"rm -rf {app} && mkdir -p {app}/Frameworks && "
            f"sed -e s/HILEN_EXECUTABLE/{self.executable}/g "
            f"-e s/HILEN_BUNDLE_ID/{self.bundle_id}/g "
            f"{native}/{loader.plist} > {app}/Info.plist && "
            f"if [ -d assets ]; then cp -R assets {app}/assets; fi && "
            f"xcrun -sdk {loader.sdk} clang -target {loader.clang_target} -fobjc-arc -Wall "
            f"{native}/hot_loader.m -framework UIKit -framework Foundation "
            f"-o {app}/{self.executable} && "
            f'cp "{library}" {app}/Frameworks/default.dylib && '
            f'cp "{profile}" {app}/embedded.mobileprovision && '
            f'security cms -D -i "{profile}" | plutil -extract Entitlements xml1 '
            f"-o {folder}/entitlements.plist - && "
            f"codesign -s {identity} --force {app}/Frameworks/default.dylib && "
            f"codesign -s {identity} --force --entitlements {folder}/entitlements.plist {app}"
        )
        run(self._in_root(line))
        return self.root / app

    # Where the engine crate keeps the loader, on the machine that builds. An app
    # takes the engine from git, so cargo is asked.
    def _native_dir(self) -> Path:
        text = capture(self._on_builder("cargo metadata --format-version 1"))
        line = next((ln for ln in text.splitlines() if ln.startswith("{")), None)
        if line is None:
            bail("cargo metadata printed no JSON")
        metadata = msgspec.json.decode(line, type=_Metadata)
        hilen = next((p for p in metadata.packages if p.name == "hilen"), None)
        if hilen is None:
            bail("the app does not depend on hilen")
        return Path(hilen.manifest_path).parent / "native/ios"

    # Puts a built library into the hot folder under a new name and points the
    # loader at it. The library is whole before the pointer changes, and the
    # pointer changes with 1 rename. `assets` is the folder that holds the
    # `assets` of the app, when they are not in the loader app.
    def publish(self, library: Path, assets: Path | None) -> str:
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns() // 1_000_000}.dylib"
        try:
            shutil.copyfile(library, self.dir / name)
        except OSError as err:
            bail(f"no library at {library}: {err}")
        pending = self.dir / "current.new"
        pending.write_text(name if assets is None else f"{name}\n{assets}", encoding="utf-8")
        pending.replace(self.dir / _POINTER)
        # The names are times, so the order of the names is the order of age.
        libraries = sorted(self.dir.glob("*.dylib"))
        for old in libraries[: max(len(libraries) - _LIBRARIES_KEPT, 0)]:
            old.unlink()
        return name

    def _boot(self, device: str) -> str:
        run(f"xcrun simctl boot {device}")
        run(f"xcrun simctl bootstatus {device} -b")
        return device

    # The simulator device to run in: a booted one of the system, or the first
    # iPhone or Apple TV there is, booted here. A far job makes a device of its
    # own, the builder is shared and a booted device there belongs to another
    # session. `release_device` deletes it again.
    def simulator(self) -> str:
        tv = self.system is System.TVOS
        job = os.environ.get(_FAR_JOB)
        if job is not None:
            device_type, runtime = (
                (_JOB_TV_DEVICE_TYPE, _JOB_TV_RUNTIME) if tv else (_JOB_DEVICE_TYPE, _JOB_RUNTIME)
            )
            return self._boot(
                capture(f"xcrun simctl create hilen-hot-{job} {device_type} {runtime}")
            )
        booted = first_device(of_system(probe("xcrun simctl list devices booted"), tv=tv))
        if booted is not None:
            return booted
        devices = of_system(probe("xcrun simctl list devices available"), tv=tv)
        wanted = _lines_with(devices, _TV_SMALL if tv else "iPhone")
        device = first_device(devices if tv and not wanted else wanted)
        if device is None:
            if tv:
                bail("no Apple TV simulator device, make one, see docs/tvos.md in hilen")
            bail("no iPhone simulator device, make one in Xcode")
        return self._boot(device)

    def release_device(self, device: str):
        if _FAR_JOB in os.environ:
            run_allow_fail(f"xcrun simctl shutdown {device}")
            run_allow_fail(f"xcrun simctl delete {device}")

    # Installs the loader and starts it on the hot folder. Gives the process id.
    def launch(self, device: str, loader: Path) -> int:
        run(f'xcrun simctl install {device} "{loader}"')
        launched = capture(
            f'SIMCTL_CHILD_HILEN_HOT_DIR="{self.dir}" xcrun simctl launch '
            f"--terminate-running-process {device} {self.bundle_id}"
        )
        # `<bundle id>: <pid>`
        try:
            return int(launched.rsplit(" ", 1)[-1].strip())
        except ValueError:
            bail(f"no process id in `{launched}`")

    # Waits until the app has written `text` into a file `name` of its data
    # folder, which the app of the hot reload lane does at its start.
    def wait_for_marker(self, device: str, name: str, text: str):
        container = capture(f"xcrun simctl get_app_container {device} {self.bundle_id} data")
        last = ""
        for _ in range(_MARKER_TRIES):
            found = probe(f'find "{container}" -name {name}').splitlines()
            if found:
                try:
                    last = Path(found[0]).read_text(encoding="utf-8")
                except OSError:
                    last = ""
                if last.strip() == text:
                    return
            time.sleep(_MARKER_POLL)
        bail(f"the app did not start `{text}`, its marker says `{last.strip()}`")

    # Waits until the loader says that it started the library `name`.
    def wait_for_start(self, name: str):
        started = self.dir / _STARTED
        last = ""
        for _ in range(_STARTED_TRIES):
            try:
                last = started.read_text(encoding="utf-8")
            except OSError:
                last = ""
            if last.strip() == name:
                return
            time.sleep(_MARKER_POLL)
        bail(f"the loader did not start {name}, it runs `{last.strip()}`")

    # Changes when a source file is saved, added or removed.
    def sources(self) -> tuple[int, float]:
        count = 0
        newest = 0.0
        for folder, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _NOT_WATCHED]
            for file in files:
                if file.startswith(".") or file in _NOT_WATCHED:
                    continue
                count += 1
                newest = max(newest, (Path(folder) / file).stat().st_mtime)
        return count, newest


# The inspect tool sends a library to a device, it runs on this Mac.
INSPECT: Final = "target/debug/hilen-inspect"


# The inspect tool of the engine repo `here`, built with the engine of that
# folder, so both sides of a send speak the same protocol. It is built again only
# after a source of the repo was saved.
def inspect_tool(here: Path) -> Path:
    hot = Hot.at(here, "HilenSwap", "hilen.swap")
    tool = here / INSPECT
    try:
        built = tool.stat().st_mtime
    except OSError:
        built = None
    if built is None or hot.sources()[1] > built:
        hot.build_tool("hilen-inspect", INSPECT)
    return tool


# The development certificate of this Mac, as the hash `codesign` takes. iOS
# loads a library on a phone only with this signature.
def sign_identity() -> str:
    lines = capture("security find-identity -v -p codesigning").splitlines()
    line = next((ln for ln in lines if "Apple Development" in ln), None)
    if line is None:
        bail("no Apple Development certificate in the keychain")
    words = line.split()
    if len(words) <= _HASH_AT:
        bail("no hash in the identity line")
    return words[_HASH_AT]


# Signs a library for a phone, in place.
def sign_library(library: Path):
    run(f'codesign -s {sign_identity()} --force "{library}"')


# The development profile Xcode made for the app `bundle_id` on `system`. A
# loader built with no Xcode project can't ask for a new one. An app has a
# profile for each system under the same id.
def development_profile(bundle_id: str, system: System) -> Path:
    platform = "iOS" if system is System.IOS else "tvOS"
    folder = Path(os.environ["HOME"]) / _PROFILES
    try:
        profiles = sorted(folder.glob("*.mobileprovision"))
    except OSError as err:
        bail(f"no profiles in {folder}: {err}")
    for path in profiles:

        def read(key: str, path: Path = path) -> str:
            return probe(
                f'security cms -D -i "{path}" 2>/dev/null | plutil -extract {key} raw - 2>/dev/null'
            ).strip()

        # The id is the team, a dot, then the bundle id.
        _, dot, app_id = read("Entitlements.application-identifier").partition(".")
        same_app = bool(dot) and app_id == bundle_id
        development = read("Entitlements.get-task-allow") == "true"
        if same_app and development and read("Platform.0") == platform:
            return path
    msg = (
        f"no {platform} development profile for {bundle_id}, "
        "build the app for a device in Xcode once"
    )
    raise ScriptError(msg)


# The paired iPhone or Apple TV, as `devicectl` names it.
def paired(system: System) -> str:
    if system is System.IOS:
        model, missing = "iPhone", "no paired iPhone, plug it in and unlock it"
    else:
        model, missing = "AppleTV", 'no paired Apple TV, see "An Apple TV" in docs/hot-reload.md'
    lines = capture("xcrun devicectl list devices").splitlines()
    line = next((ln for ln in lines if "available" in ln and model in ln), None)
    if line is None:
        bail(missing)
    found = next(
        (w for w in line.split() if len(w) == _ID_LENGTH and w.count("-") == _ID_DASHES), None
    )
    if found is None:
        bail("no device id in the devicectl line")
    return found


# The red, green and blue of the pixel in the middle of the screen.
def screen_color(device: str) -> tuple[int, int, int]:
    file = Path(tempfile.gettempdir()) / f"hilen-hot-{device}.bmp"
    run_quiet(f'xcrun simctl io {device} screenshot --type=bmp "{file}"')
    return middle_of_bmp(file.read_bytes())


# A bmp holds its pixels plain, blue first, so no image library is needed.
def middle_of_bmp(data: bytes) -> tuple[int, int, int]:
    def number(at: int) -> int:
        field = data[at : at + _BMP_FIELD]
        if len(field) != _BMP_FIELD:
            bail("the bmp is cut off")
        return int.from_bytes(field, "little", signed=True)

    start = number(10)
    width = number(18)
    height = number(22)
    pixel = number(28) % 65536 // 8
    # Every row is filled up to 4 bytes. A negative height counts the rows from
    # the top, the middle row is the same one either way.
    row = (width * pixel + 3) // 4 * 4
    at = start + abs(height) // 2 * row + width // 2 * pixel
    found = data[at : at + _BMP_PIXEL]
    if len(found) != _BMP_PIXEL:
        bail("the bmp is cut off")
    return found[2], found[1], found[0]


def thread_count(pid: int) -> int:
    return max(len(run_quiet(f"ps -M {pid}").splitlines()) - 1, 0)


# The memory the process holds, in MB.
def memory_mb(pid: int) -> int:
    kilobytes = run_quiet(f"ps -o rss= -p {pid}")
    try:
        return int(kilobytes.strip()) // _KIB
    except ValueError:
        bail(f"no memory size in `{kilobytes}`")


def open_files(pid: int) -> int:
    return max(len(run_quiet(f"lsof -p {pid}").splitlines()) - 1, 0)


def is_alive(pid: int) -> bool:
    return bool(probe(f"ps -p {pid} -o pid=").strip())


def _lines_with(text: str, word: str) -> str:
    return "\n".join(line for line in text.splitlines() if word in line)


# The devices of a `simctl` list that are Apple TVs, or with `tv` false the ones
# that are not. The name of a device tells nothing, a person picks it.
def of_system(text: str, *, tv: bool) -> str:
    in_tv = False
    devices: list[str] = []
    for line in text.splitlines():
        if line.startswith(_SECTION):
            in_tv = _TV_SECTION in line
        elif in_tv == tv:
            devices.append(line)
    return "\n".join(devices)


def _is_hex_id(text: str) -> bool:
    return len(text) == _ID_LENGTH and all(c in "0123456789abcdefABCDEF-" for c in text)


# The id of the first device in a `simctl` list. The name of a device can have
# brackets of its own, like `Apple TV 4K (3rd generation)`.
def first_device(text: str) -> str | None:
    for line in text.splitlines():
        for part in line.split("(")[1:]:
            if _is_hex_id(part[:_ID_LENGTH]):
                return part[:_ID_LENGTH]
    return None
