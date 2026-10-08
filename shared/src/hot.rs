//! Hot reload of an app in the iOS simulator, see docs/hot-reload.md in hilen.
//!
//! The app is built as 1 dynamic library. A small loader app is installed
//! once and loads the library from a folder on this Mac. Every new build
//! lands in that folder under a new name, and the loader swaps to it while
//! the app keeps running.
//!
//! The simulator runs on the Mac the script is started on. The builds run
//! through `far` when it is installed, on a build machine, and here otherwise.

use std::{
    fs::{copy, create_dir_all, read, read_dir, read_to_string, remove_file, rename, write},
    path::{Path, PathBuf},
    thread::sleep,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use anyhow::{Context, Result, bail};
use serde::Deserialize;

use crate::{
    config::Config,
    run::{capture, probe, run, run_allow_fail, run_quiet},
};

/// The simulator of an Apple Silicon Mac. No Rosetta, which keeps a
/// translation of every library a process ever loaded.
pub const TARGET: &str = "aarch64-apple-ios-sim";
/// A real iPhone, see "A real iPhone" in docs/hot-reload.md.
const DEVICE_TARGET: &str = "aarch64-apple-ios";
/// Where Xcode keeps the provisioning profiles it made.
const PROFILES: &str = "Library/Developer/Xcode/UserData/Provisioning Profiles";
/// No arm64 simulator is older than iOS 14.
const IOS_MINIMUM: &str = "14.0";
/// The flag takes rayon out of the engine, its threads never end.
const HOT_CFG: &str = r#"["--cfg","hilen_hot"]"#;
/// The folder of the libraries and the pointer file, below the repo root.
const HOT_DIR: &str = "target/hot/lib";
const POINTER: &str = "current";
/// The loader writes the name of the library it started into this file.
const STARTED: &str = "started";
/// The source an app takes the engine from. A library that must carry the
/// engine of a folder on disk is built with this source pointed there.
const ENGINE_GIT: &str = "https://github.com/hilen/hilen.git";
/// The lock file of an app is put aside here while the engine of a folder is
/// built in, so the build leaves the repo of the app as it was.
const KEPT_LOCK: &str = "target/hot-Cargo.lock";
const STARTED_TRIES: usize = 240;
/// The running app has the newest library mapped and loads the next one
/// before it lets go, so 2 files are in use at most.
const LIBRARIES_KEPT: usize = 3;
/// Set inside a far job, see far.md in the comb repo.
const FAR_JOB: &str = "FAR_JOB";
/// The device of a far job, the same one the UI test lane makes.
const JOB_DEVICE_TYPE: &str = "com.apple.CoreSimulator.SimDeviceType.iPhone-8";
const JOB_RUNTIME: &str = "com.apple.CoreSimulator.SimRuntime.iOS-16-4";
const MARKER_POLL: Duration = Duration::from_millis(250);
const MARKER_TRIES: usize = 120;
/// Folders a change in which is no change of the app.
const NOT_WATCHED: &[&str] = &["target", "build", "mobile", "dist", "node_modules", "bench"];

/// `cargo metadata`, only what is read here.
#[derive(Deserialize)]
struct Metadata {
    packages: Vec<Package>,
}

#[derive(Deserialize)]
struct Package {
    name:          String,
    manifest_path: PathBuf,
}

pub struct Hot {
    /// The builds go to a build machine.
    far:        bool,
    root:       PathBuf,
    /// The name of the loader app and of its executable.
    executable: String,
    bundle_id:  String,
    /// The folder of the libraries and the pointer file.
    dir:        PathBuf,
    /// The repo of an engine on disk that the library is built with, in
    /// place of the engine the app names.
    engine:     Option<PathBuf>,
    /// The library is for a real iPhone, not for the simulator.
    device:     bool,
}

impl Hot {
    pub fn new(config: &Config) -> Result<Self> {
        Self::named(&config.project_name, &format!("{}.hot", config.bundle_id))
    }

    /// `bundle_id` is a name of its own, so the loader does not replace the
    /// normal app in the simulator.
    pub fn named(executable: &str, bundle_id: &str) -> Result<Self> {
        Ok(Self::at(&std::env::current_dir()?, executable, bundle_id))
    }

    /// Like `named`, for the repo at `root` in place of the current folder.
    pub fn at(root: &Path, executable: &str, bundle_id: &str) -> Self {
        // Inside a far job this machine is the builder already.
        let on_builder = std::env::var(FAR_JOB).is_ok();
        Self {
            far:        !on_builder && !probe("command -v far").trim().is_empty(),
            root:       root.to_path_buf(),
            executable: executable.to_string(),
            bundle_id:  bundle_id.to_string(),
            dir:        root.join(HOT_DIR),
            engine:     None,
            device:     false,
        }
    }

    /// The library is built for a real iPhone.
    #[must_use]
    pub fn for_device(mut self) -> Self {
        self.device = true;
        self
    }

    fn target(&self) -> &'static str {
        if self.device { DEVICE_TARGET } else { TARGET }
    }

    /// The cargo argument that adds the hot flag to the compiler flags.
    /// Cargo takes the flags of a target and then ignores the general
    /// ones, so the flag has to go where the repo keeps its own.
    fn hot_flag(&self) -> String {
        let target = self.target();
        let config = read_to_string(self.root.join(".cargo/config.toml")).unwrap_or_default();
        let own_target_flags = toml::from_str::<toml::Table>(&config)
            .ok()
            .and_then(|config| config.get("target")?.get(target)?.get("rustflags").cloned())
            .is_some();
        if own_target_flags {
            format!("--config 'target.{target}.rustflags={HOT_CFG}'")
        } else {
            format!("--config 'build.rustflags={HOT_CFG}'")
        }
    }

    /// Another folder for the libraries, below the repo root.
    #[must_use]
    pub fn with_dir(mut self, dir: &str) -> Self {
        self.dir = self.root.join(dir);
        self
    }

    /// The library is built with the engine of the repo at `engine`.
    #[must_use]
    pub fn with_engine(mut self, engine: &Path) -> Self {
        self.engine = Some(engine.to_path_buf());
        self
    }

    pub fn bundle_id(&self) -> &str {
        &self.bundle_id
    }

    /// A shell line in the repo, on this machine.
    fn in_root(&self, line: &str) -> String {
        format!("cd \"{}\" && {line}", self.root.display())
    }

    /// A shell line in the repo, on the machine that builds.
    fn on_builder(&self, line: &str) -> String {
        if self.far {
            self.in_root(&format!("far '{}'", line.replace('\'', r"'\''")))
        } else {
            self.in_root(line)
        }
    }

    fn fetch(&self, path: &str) -> Result<()> {
        if self.far {
            run(&self.in_root(&format!("far get {path}")))?;
        }
        Ok(())
    }

    /// The builder gets the engine folder as it is here now. A job of the
    /// app sends only the repo of the app.
    fn send_engine(&self) -> Result<()> {
        if let Some(engine) = &self.engine
            && self.far
        {
            run(&format!("cd \"{}\" && far true", engine.display()))?;
        }
        Ok(())
    }

    pub fn prepare(&self) -> Result<()> {
        run(&self.on_builder(&format!("rustup target add {}", self.target())))
    }

    /// Builds `package` as 1 dynamic library with the engine inside and
    /// brings it here. `features` are more cargo features of the package.
    pub fn build_library(&self, package: &str, features: &str) -> Result<PathBuf> {
        let exports = format!("export CFLAGS= SDKROOT= IPHONEOS_DEPLOYMENT_TARGET={IOS_MINIMUM}");
        let target = self.target();
        let hot_flag = self.hot_flag();
        let cargo = format!(
            "cargo rustc -p {package} --lib --target {target} --crate-type cdylib --features hilen/hot{features} {hot_flag}"
        );
        let line = match &self.engine {
            Some(engine) => {
                // The same relative path is right on the builder, far keeps
                // the folders as they lie here.
                let path = relative(&self.root, &engine.join("hilen"));
                let path = path.display();
                let patch = format!(r#"--config 'patch."{ENGINE_GIT}".hilen.path="{path}"'"#);
                // The new source of the engine changes the lock file.
                let keep = format!("mkdir -p target && cp Cargo.lock {KEPT_LOCK}");
                let restore = format!("status=$?; cp {KEPT_LOCK} Cargo.lock; exit $status");
                format!("{exports}; {keep} && {cargo} {patch}; {restore}")
            }
            None => format!("{exports}; {cargo}"),
        };
        self.send_engine()?;
        run(&self.on_builder(&line))?;

        let library = format!("target/{target}/debug/lib{}.dylib", package.replace('-', "_"));
        self.fetch(&library)?;
        Ok(self.root.join(library))
    }

    /// Builds the loader app on the builder, from the 2 files of the engine
    /// crate, and brings it here.
    pub fn build_loader(&self) -> Result<PathBuf> {
        let native = self.native_dir()?;
        let native = native.display();
        let executable = &self.executable;
        let bundle_id = &self.bundle_id;
        let app = format!("target/hot/{executable}.app");
        let line = format!(
            "rm -rf {app} && mkdir -p {app} && \
sed -e s/HILEN_EXECUTABLE/{executable}/g -e s/HILEN_BUNDLE_ID/{bundle_id}/g {native}/hot_loader.plist > {app}/Info.plist && \
if [ -d assets ]; then cp -R assets {app}/assets; fi && \
xcrun -sdk iphonesimulator clang -target arm64-apple-ios{IOS_MINIMUM}-simulator -fobjc-arc -Wall {native}/hot_loader.m \
-framework UIKit -framework Foundation -o {app}/{executable} && \
codesign -s - --force {app}"
        );
        run(&self.on_builder(&line))?;
        self.fetch(&app)?;
        Ok(self.root.join(app))
    }

    /// Builds a program of this repo that has to run on this Mac and
    /// brings it here.
    pub fn build_tool(&self, package: &str, program: &str) -> Result<()> {
        run(&self.on_builder(&format!("cargo build -p {package}")))?;
        self.fetch(program)
    }

    /// Builds the loader app for a real iPhone, here and not on a builder,
    /// since the development certificate is on this Mac. `library` is the
    /// app the loader shows when nothing was sent to it, it goes into the
    /// loader app. Run from the hilen repo, the loader source is taken from
    /// this folder.
    pub fn build_device_loader(&self, library: &Path) -> Result<PathBuf> {
        let executable = &self.executable;
        let bundle_id = &self.bundle_id;
        let native = "hilen/native/ios";
        let folder = "target/hot/device";
        let app = format!("{folder}/{executable}.app");
        let profile = development_profile(bundle_id)?;
        let profile = profile.display();
        let identity = sign_identity()?;
        let library = library.display();
        let line = format!(
            "rm -rf {app} && mkdir -p {app}/Frameworks && \
sed -e s/HILEN_EXECUTABLE/{executable}/g -e s/HILEN_BUNDLE_ID/{bundle_id}/g {native}/hot_loader.plist > {app}/Info.plist && \
if [ -d assets ]; then cp -R assets {app}/assets; fi && \
xcrun -sdk iphoneos clang -target arm64-apple-ios{IOS_MINIMUM} -fobjc-arc -Wall {native}/hot_loader.m \
-framework UIKit -framework Foundation -o {app}/{executable} && \
cp \"{library}\" {app}/Frameworks/default.dylib && \
cp \"{profile}\" {app}/embedded.mobileprovision && \
security cms -D -i \"{profile}\" | plutil -extract Entitlements xml1 -o {folder}/entitlements.plist - && \
codesign -s {identity} --force {app}/Frameworks/default.dylib && \
codesign -s {identity} --force --entitlements {folder}/entitlements.plist {app}"
        );
        run(&self.in_root(&line))?;
        Ok(self.root.join(app))
    }

    /// Where the engine crate keeps the loader, on the machine that builds.
    /// An app takes the engine from git, so cargo is asked.
    fn native_dir(&self) -> Result<PathBuf> {
        let text = capture(&self.on_builder("cargo metadata --format-version 1"))?;
        let json = text.lines().find(|line| line.starts_with('{')).context("cargo metadata printed no JSON")?;
        let metadata: Metadata = serde_json::from_str(json)?;
        let hilen = metadata
            .packages
            .iter()
            .find(|package| package.name == "hilen")
            .context("the app does not depend on hilen")?;
        let dir = hilen.manifest_path.parent().context("the hilen manifest has no folder")?;
        Ok(dir.join("native/ios"))
    }

    pub fn dir(&self) -> PathBuf {
        self.dir.clone()
    }

    /// Puts a built library into the hot folder under a new name and points
    /// the loader at it. The library is whole before the pointer changes,
    /// and the pointer changes with 1 rename. `assets` is the folder that
    /// holds the `assets` of the app, when they are not in the loader app.
    pub fn publish(&self, library: &Path, assets: Option<&Path>) -> Result<String> {
        let dir = self.dir();
        create_dir_all(&dir)?;

        let stamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
        let name = format!("{stamp}.dylib");
        copy(library, dir.join(&name)).with_context(|| format!("no library at {}", library.display()))?;

        let pending = dir.join("current.new");
        let pointer = match assets {
            Some(assets) => format!("{name}\n{}", assets.display()),
            None => name.clone(),
        };
        write(&pending, pointer)?;
        rename(&pending, dir.join(POINTER))?;

        self.drop_old_libraries(&dir)?;
        Ok(name)
    }

    fn drop_old_libraries(&self, dir: &Path) -> Result<()> {
        let mut libraries = vec![];
        for entry in read_dir(dir)? {
            let path = entry?.path();
            if path.extension().is_some_and(|extension| extension == "dylib") {
                libraries.push(path);
            }
        }
        // The names are times, so the order of the names is the order of age.
        libraries.sort();
        let extra = libraries.len().saturating_sub(LIBRARIES_KEPT);
        for old in libraries.iter().take(extra) {
            remove_file(old)?;
        }
        Ok(())
    }

    /// The simulator device to run in: one that is booted, or the first
    /// iPhone there is, booted here. A far job makes a device of its own,
    /// the builder is shared and a booted device there belongs to another
    /// session. `release_device` deletes it again.
    pub fn device(&self) -> Result<String> {
        if let Ok(job) = std::env::var(FAR_JOB) {
            let device = capture(&format!("xcrun simctl create hilen-hot-{job} {JOB_DEVICE_TYPE} {JOB_RUNTIME}"))?;
            run(&format!("xcrun simctl boot {device}"))?;
            run(&format!("xcrun simctl bootstatus {device} -b"))?;
            return Ok(device);
        }
        if let Some(booted) = first_device(&probe("xcrun simctl list devices booted")) {
            return Ok(booted);
        }
        let devices = probe("xcrun simctl list devices available");
        let iphones: String = devices.lines().filter(|line| line.contains("iPhone")).collect::<Vec<_>>().join("\n");
        let Some(device) = first_device(&iphones) else {
            bail!("no iPhone simulator device, make one in Xcode");
        };
        run(&format!("xcrun simctl boot {device}"))?;
        run(&format!("xcrun simctl bootstatus {device} -b"))?;
        Ok(device)
    }

    pub fn release_device(&self, device: &str) {
        if std::env::var(FAR_JOB).is_ok() {
            run_allow_fail(&format!("xcrun simctl shutdown {device}"));
            run_allow_fail(&format!("xcrun simctl delete {device}"));
        }
    }

    /// Installs the loader and starts it on the hot folder. Prints the
    /// process id.
    pub fn launch(&self, device: &str, loader: &Path) -> Result<u32> {
        run(&format!("xcrun simctl install {device} \"{}\"", loader.display()))?;
        let launched = capture(&format!(
            "SIMCTL_CHILD_HILEN_HOT_DIR=\"{}\" xcrun simctl launch --terminate-running-process {device} {}",
            self.dir().display(),
            self.bundle_id
        ))?;
        // `<bundle id>: <pid>`
        let pid = launched.rsplit(' ').next().unwrap_or_default().trim();
        pid.parse().with_context(|| format!("no process id in `{launched}`"))
    }

    /// Waits until the app has written `text` into a file `name` of its data
    /// folder, which the app of the hot reload lane does at its start.
    pub fn wait_for_marker(&self, device: &str, name: &str, text: &str) -> Result<()> {
        let container =
            capture(&format!("xcrun simctl get_app_container {device} {} data", self.bundle_id))?;
        let mut last = String::new();
        for _ in 0..MARKER_TRIES {
            let found = probe(&format!("find \"{container}\" -name {name}"));
            if let Some(path) = found.lines().next() {
                last = read_to_string(path).unwrap_or_default();
                if last.trim() == text {
                    return Ok(());
                }
            }
            sleep(MARKER_POLL);
        }
        bail!("the app did not start `{text}`, its marker says `{}`", last.trim())
    }

    /// Waits until the loader says that it started the library `name`.
    pub fn wait_for_start(&self, name: &str) -> Result<()> {
        let started = self.dir.join(STARTED);
        let mut last = String::new();
        for _ in 0..STARTED_TRIES {
            last = read_to_string(&started).unwrap_or_default();
            if last.trim() == name {
                return Ok(());
            }
            sleep(MARKER_POLL);
        }
        bail!("the loader did not start {name}, it runs `{}`", last.trim())
    }

    /// Changes when a source file is saved, added or removed.
    pub fn sources(&self) -> Result<(usize, SystemTime)> {
        let mut state = (0, UNIX_EPOCH);
        walk(&self.root, &mut state)?;
        Ok(state)
    }
}

/// The development certificate of this Mac, as the hash `codesign` takes.
/// iOS loads a library on a phone only with this signature.
pub fn sign_identity() -> Result<String> {
    let identities = capture("security find-identity -v -p codesigning")?;
    let line = identities
        .lines()
        .find(|line| line.contains("Apple Development"))
        .context("no Apple Development certificate in the keychain")?;
    Ok(line.split_whitespace().nth(1).context("no hash in the identity line")?.to_string())
}

/// Signs a library for a phone, in place.
pub fn sign_library(library: &Path) -> Result<()> {
    run(&format!("codesign -s {} --force \"{}\"", sign_identity()?, library.display()))
}

/// The development profile Xcode made for the app `bundle_id`. A loader
/// built with no Xcode project cannot ask for a new one.
fn development_profile(bundle_id: &str) -> Result<PathBuf> {
    let folder = PathBuf::from(std::env::var("HOME")?).join(PROFILES);
    for entry in read_dir(&folder).with_context(|| format!("no profiles in {}", folder.display()))? {
        let path = entry?.path();
        if path.extension().is_none_or(|extension| extension != "mobileprovision") {
            continue;
        }
        let read = |key: &str| {
            probe(&format!(
                "security cms -D -i \"{}\" 2>/dev/null | plutil -extract Entitlements.{key} raw - 2>/dev/null",
                path.display()
            ))
        };
        // The id is the team, a dot, then the bundle id.
        let same_app = read("application-identifier").trim().split_once('.').is_some_and(|(_, id)| id == bundle_id);
        if same_app && read("get-task-allow").trim() == "true" {
            return Ok(path);
        }
    }
    bail!("no development profile for {bundle_id}, build the app for a phone in Xcode once")
}

/// The iPhone that is connected and paired, as `devicectl` names it.
pub fn phone() -> Result<String> {
    let devices = capture("xcrun devicectl list devices")?;
    let line = devices
        .lines()
        .find(|line| line.contains("available") && line.contains("iPhone"))
        .context("no paired iPhone, plug it in and unlock it")?;
    line.split_whitespace()
        .find(|word| word.len() == 36 && word.matches('-').count() == 4)
        .map(str::to_string)
        .context("no device id in the devicectl line")
}

/// The red, green and blue of the pixel in the middle of the screen.
pub fn screen_color(device: &str) -> Result<(u8, u8, u8)> {
    let file = std::env::temp_dir().join(format!("hilen-hot-{device}.bmp"));
    let file_text = file.display();
    run_quiet(&format!("xcrun simctl io {device} screenshot --type=bmp \"{file_text}\""))?;
    middle_of_bmp(&read(&file)?)
}

/// A bmp holds its pixels plain, blue first, so no image crate is needed.
fn middle_of_bmp(bytes: &[u8]) -> Result<(u8, u8, u8)> {
    let number = |at: usize| -> Result<i64> {
        let field: [u8; 4] = bytes.get(at..at + 4).context("the bmp is cut off")?.try_into()?;
        Ok(i64::from(i32::from_le_bytes(field)))
    };
    let start = number(10)?;
    let width = number(18)?;
    let height = number(22)?;
    let pixel = number(28)? % 65536 / 8;
    // Every row is filled up to 4 bytes. A negative height counts the rows
    // from the top, the middle row is the same one either way.
    let row = (width * pixel + 3) / 4 * 4;
    let at = usize::try_from(start + height.abs() / 2 * row + width / 2 * pixel)?;
    let found = bytes.get(at..at + 3).context("the bmp is cut off")?;
    Ok((found[2], found[1], found[0]))
}

pub fn thread_count(pid: u32) -> Result<usize> {
    let threads = run_quiet(&format!("ps -M {pid}"))?;
    Ok(threads.lines().count().saturating_sub(1))
}

/// The memory the process holds, in MB.
pub fn memory_mb(pid: u32) -> Result<u64> {
    let kilobytes = run_quiet(&format!("ps -o rss= -p {pid}"))?;
    let kilobytes: u64 = kilobytes.trim().parse().with_context(|| format!("no memory size in `{kilobytes}`"))?;
    Ok(kilobytes / 1024)
}

pub fn open_files(pid: u32) -> Result<usize> {
    let files = run_quiet(&format!("lsof -p {pid}"))?;
    Ok(files.lines().count().saturating_sub(1))
}

pub fn is_alive(pid: u32) -> bool {
    !probe(&format!("ps -p {pid} -o pid=")).trim().is_empty()
}

fn first_device(list: &str) -> Option<String> {
    list.lines().find_map(|line| {
        let start = line.find('(')? + 1;
        let id = line.get(start..start + 36)?;
        let is_id = id.len() == 36 && id.chars().all(|c| c.is_ascii_hexdigit() || c == '-');
        is_id.then(|| id.to_string())
    })
}

/// The path from the folder `from` to `to`, both full paths.
fn relative(from: &Path, to: &Path) -> PathBuf {
    let from: Vec<_> = from.components().collect();
    let to: Vec<_> = to.components().collect();
    let shared = from.iter().zip(&to).take_while(|(a, b)| a == b).count();
    let mut path = PathBuf::new();
    for _ in shared..from.len() {
        path.push("..");
    }
    for part in &to[shared..] {
        path.push(part);
    }
    path
}

fn walk(dir: &Path, state: &mut (usize, SystemTime)) -> Result<()> {
    for entry in read_dir(dir)? {
        let entry = entry?;
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with('.') || NOT_WATCHED.contains(&name.as_ref()) {
            continue;
        }
        let meta = entry.metadata()?;
        if meta.is_dir() {
            walk(&entry.path(), state)?;
            continue;
        }
        state.0 += 1;
        state.1 = state.1.max(meta.modified()?);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_middle_pixel_of_a_bmp_is_read() -> Result<()> {
        // 3 by 3 pixels of 3 bytes, rows filled up to 12 bytes, all black
        // but the middle one.
        let mut bmp = vec![0; 54 + 3 * 12];
        bmp[10] = 54;
        bmp[18] = 3;
        bmp[22] = 3;
        bmp[28] = 24;
        let middle = 54 + 12 + 3;
        bmp[middle..middle + 3].copy_from_slice(&[10, 20, 30]);
        assert_eq!(middle_of_bmp(&bmp)?, (30, 20, 10));
        Ok(())
    }

    #[test]
    fn the_engine_folder_is_named_from_the_repo_of_an_app() {
        let path = relative(Path::new("/dev/apps/skaityk"), Path::new("/dev/hilen/hilen"));
        assert_eq!(path, Path::new("../../hilen/hilen"));
    }

    #[test]
    fn a_device_id_is_read_from_a_simctl_line() {
        let list = "-- iOS 16.4 --\n    iPhone 8 (81A051F7-CB2B-47D2-80FA-8F0AB4CC8B02) (Booted)";
        assert_eq!(first_device(list).as_deref(), Some("81A051F7-CB2B-47D2-80FA-8F0AB4CC8B02"));
        assert_eq!(first_device("== Devices ==\n-- iOS 16.4 --"), None);
    }
}
