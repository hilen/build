//! 1 loader app in the iOS simulator that swaps between several apps,
//! `make swap`, see docs/hot-reload.md in hilen.
//!
//! Every app is built as 1 dynamic library, like for `make hot`. The loader
//! starts the first one. Nothing swaps by itself: `to` puts the library of
//! another app in front of the loader, which stops the app that runs and
//! starts the other one in the same process.
//!
//! Every command returns, so a person and an agent use it the same way. What
//! runs is kept in a file between the commands.

use std::{
    env::current_dir,
    fs::{create_dir_all, read_to_string, remove_file, write},
    path::{Path, PathBuf},
    thread::sleep,
    time::Duration,
};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};

use crate::{
    config,
    hot::{Hot, is_alive, memory_mb, open_files, phone, sign_library, thread_count},
    run::{run, run_allow_fail},
};

const EXECUTABLE: &str = "HilenSwap";
const BUNDLE_ID: &str = "hilen.swap";
/// The libraries, the pointer file and the state, below the repo root.
const DIR: &str = "target/hot/swap";
const STATE: &str = "state.json";
const PROJECT_FILE: &str = "hilen.toml";
/// An app that just started still draws its first frames and loads its
/// first data, the numbers of the process are read after that.
const SETTLE: Duration = Duration::from_secs(3);
/// The name of the loader app on a phone.
const PHONE_EXECUTABLE: &str = "Hilen";
/// The inspect tool sends a library to the phone, it has to run on this Mac.
const INSPECT: &str = "target/debug/hilen-inspect";

/// What runs, kept between the commands.
#[derive(Serialize, Deserialize)]
struct State {
    device:  String,
    pid:     u32,
    /// The name of the app on the screen.
    current: String,
    apps:    Vec<App>,
}

#[derive(Serialize, Deserialize)]
struct App {
    /// The cargo package, also the name `to` takes.
    name: String,
    /// The repo of the app, the folder with its `hilen.toml` and `assets`.
    root: PathBuf,
}

/// `Cargo.toml`, only what is read here.
#[derive(Deserialize)]
struct Manifest {
    package: Package,
}

#[derive(Deserialize)]
struct Package {
    name: String,
}

impl App {
    /// The app whose crate is in `folder`.
    fn find(folder: &str) -> Result<Self> {
        let folder = Path::new(folder).canonicalize().with_context(|| format!("no folder {folder}"))?;
        let manifest = folder.join("Cargo.toml");
        let text = read_to_string(&manifest).with_context(|| format!("no {}", manifest.display()))?;
        let manifest: Manifest =
            toml::from_str(&text).with_context(|| format!("{} names no package", manifest.display()))?;
        let root = folder
            .ancestors()
            .find(|dir| dir.join(PROJECT_FILE).is_file())
            .with_context(|| format!("no {PROJECT_FILE} in {} or above it", folder.display()))?;
        Ok(Self {
            name: manifest.package.name,
            root: root.to_path_buf(),
        })
    }
}

pub struct Swap {
    /// The repo the command runs in. The loader is built from its engine.
    here:   PathBuf,
    loader: Hot,
}

impl Swap {
    pub fn new() -> Result<Self> {
        let here = current_dir()?;
        let loader = Hot::at(&here, EXECUTABLE, BUNDLE_ID).with_dir(DIR);
        Ok(Self { here, loader })
    }

    /// Builds every app, starts the loader and the first app in it.
    pub fn start(&self, folders: &[String]) -> Result<()> {
        if let Ok(state) = self.load()
            && is_alive(state.pid)
        {
            bail!("process {} still runs {}, `stop` it first", state.pid, state.current);
        }

        let mut apps: Vec<App> = vec![];
        for folder in folders {
            let app = App::find(folder)?;
            if apps.iter().any(|other| other.name == app.name) {
                bail!("{} is named 2 times", app.name);
            }
            apps.push(app);
        }
        let Some(first) = apps.first() else {
            bail!("no app folder given");
        };

        let mut libraries = vec![];
        for app in &apps {
            step(&format!("building {}", app.name));
            libraries.push(self.build(app)?);
        }

        step("building the loader");
        let loader = self.loader.build_loader()?;

        step(&format!("starting {}", first.name));
        let name = self.loader.publish(&libraries[0], Some(&first.root))?;
        let device = self.loader.device()?;
        // A device booted from the command line has no window.
        run(&format!("open -a Simulator --args -CurrentDeviceUDID {device}"))?;
        let pid = self.loader.launch(&device, &loader)?;
        let state = State {
            device,
            pid,
            current: first.name.clone(),
            apps,
        };
        self.save(&state)?;
        self.loader.wait_for_start(&name)?;
        sleep(SETTLE);
        report(&state)
    }

    /// Builds the app `name` again and swaps the running process to it.
    pub fn to(&self, name: &str) -> Result<()> {
        let mut state = self.load()?;
        if !is_alive(state.pid) {
            bail!("process {} is gone, `start` again", state.pid);
        }
        let Some(app) = state.apps.iter().find(|app| app.name == name) else {
            bail!("no app {name}, started with: {}", names(&state.apps));
        };

        step(&format!("building {name}"));
        let library = self.build(app)?;

        step(&format!("swapping from {} to {name}", state.current));
        let published = self.loader.publish(&library, Some(&app.root))?;
        self.loader.wait_for_start(&published)?;
        state.current = name.to_string();
        self.save(&state)?;
        sleep(SETTLE);
        report(&state)
    }

    pub fn status(&self) -> Result<()> {
        report(&self.load()?)
    }

    pub fn stop(&self) -> Result<()> {
        let state = self.load()?;
        run_allow_fail(&format!("xcrun simctl terminate {} {BUNDLE_ID}", state.device));
        remove_file(self.state_file())?;
        step(&format!("stopped process {}", state.pid));
        Ok(())
    }

    /// Builds the loader for a real iPhone with the app of this repo
    /// inside, installs it on the paired phone and starts it. The loader
    /// has the bundle id of this repo, see "A real iPhone" in
    /// docs/hot-reload.md.
    pub fn phone_install(&self) -> Result<()> {
        let config = config::read()?;
        let app = App {
            name: config.app_name,
            root: self.here.clone(),
        };

        step(&format!("building {} for the phone", app.name));
        let library = self.build_for_phone(&app)?;

        step("building the loader");
        let loader = Hot::at(&self.here, PHONE_EXECUTABLE, &config.bundle_id).build_device_loader(&library)?;

        step("installing on the phone");
        let device = phone()?;
        run(&format!("xcrun devicectl device install app --device {device} \"{}\"", loader.display()))?;
        run(&format!(
            "xcrun devicectl device process launch --device {device} --terminate-existing {}",
            config.bundle_id
        ))
    }

    /// Builds the app in `folder` and swaps the loader on the phone to it.
    pub fn phone_to(&self, folder: &str) -> Result<()> {
        let app = App::find(folder)?;

        step(&format!("building {} for the phone", app.name));
        let library = self.build_for_phone(&app)?;
        sign_library(&library)?;

        step(&format!("sending {} to the phone", app.name));
        let inspect = self.inspect()?;
        let assets = app.root.join("assets");
        let assets = if assets.is_dir() { format!(" --assets \"{}\"", assets.display()) } else { String::new() };
        run(&format!("\"{}\" hot-send \"{}\" {}{assets}", inspect.display(), library.display(), app.name))
    }

    pub fn phone_status(&self) -> Result<()> {
        run(&format!("\"{}\" hot-status", self.inspect()?.display()))
    }

    /// The inspect tool of this repo, built with the engine of this folder,
    /// so both sides of a send speak the same protocol.
    fn inspect(&self) -> Result<PathBuf> {
        let hot = Hot::at(&self.here, EXECUTABLE, BUNDLE_ID);
        hot.build_tool("hilen-inspect", INSPECT)?;
        Ok(self.here.join(INSPECT))
    }

    fn build_for_phone(&self, app: &App) -> Result<PathBuf> {
        let hot = self.with_engine(Hot::at(&app.root, EXECUTABLE, BUNDLE_ID).for_device(), app);
        hot.prepare()?;
        hot.build_library(&app.name, "")
    }

    /// Run from the engine repo, an app of another repo gets the engine
    /// of this folder, so both sides of a swap carry the same engine.
    fn with_engine(&self, hot: Hot, app: &App) -> Hot {
        let engine_here = self.here.join("hilen/Cargo.toml").is_file();
        if engine_here && app.root != self.here {
            hot.with_engine(&self.here)
        } else {
            hot
        }
    }

    fn build(&self, app: &App) -> Result<PathBuf> {
        let hot = Hot::at(&app.root, EXECUTABLE, BUNDLE_ID);
        let hot = self.with_engine(hot, app);
        hot.prepare()?;
        hot.build_library(&app.name, "")
    }

    fn state_file(&self) -> PathBuf {
        self.loader.dir().join(STATE)
    }

    fn load(&self) -> Result<State> {
        let text = read_to_string(self.state_file()).context("nothing runs, `start` first")?;
        Ok(serde_json::from_str(&text)?)
    }

    fn save(&self, state: &State) -> Result<()> {
        create_dir_all(self.loader.dir())?;
        write(self.state_file(), serde_json::to_string_pretty(state)?)?;
        Ok(())
    }
}

fn step(message: &str) {
    println!("\n[swap] {message}");
}

fn names(apps: &[App]) -> String {
    apps.iter().map(|app| app.name.as_str()).collect::<Vec<_>>().join(", ")
}

/// The app on the screen and what the process holds. A number that grows
/// from swap to swap is something an old library did not give back.
fn report(state: &State) -> Result<()> {
    println!();
    println!("[swap] app      {}", state.current);
    println!("[swap] apps     {}", names(&state.apps));
    if !is_alive(state.pid) {
        println!("[swap] process  {}, gone", state.pid);
        return Ok(());
    }
    println!("[swap] process  {}", state.pid);
    println!("[swap] threads  {}", thread_count(state.pid)?);
    println!("[swap] memory   {} MB", memory_mb(state.pid)?);
    println!("[swap] files    {}", open_files(state.pid)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{env::temp_dir, fs::remove_dir_all, process::id};

    use super::*;

    #[test]
    fn an_app_is_found_from_the_folder_of_its_crate() -> Result<()> {
        let dir = temp_dir().join(format!("hilen-swap-test-{}", id()));
        let crate_dir = dir.join("crates/game");
        create_dir_all(&crate_dir)?;
        write(dir.join(PROJECT_FILE), "project_name = \"game\"")?;
        write(crate_dir.join("Cargo.toml"), "[package]\nname = \"the-game\"")?;

        let app = App::find(&crate_dir.display().to_string())?;
        assert_eq!(app.name, "the-game");
        assert_eq!(app.root, dir.canonicalize()?);

        remove_dir_all(dir)?;
        Ok(())
    }
}
