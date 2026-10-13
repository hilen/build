//! A paired iPhone, iPad or Apple TV that runs the hot loader, `make
//! device`, see "A real device" in docs/hot-reload.md of hilen.
//!
//! The device is picked through `hilen-inspect devices`, which reads the
//! list of Xcode. Every command for it then goes to that device by its id,
//! never to whatever hot build a search of the network finds first.

use std::{
    env::{set_current_dir, var},
    fs::{create_dir_all, read_to_string, write},
    path::{Path, PathBuf},
    thread::sleep,
    time::Duration,
};

use anyhow::{Context, Result, bail};

use crate::{
    hot::System,
    run::{capture, probe, run},
    swap::{Swap, inspect_tool},
};

/// The device the last `make device` of an app went to, below its root.
/// Not `target/hot/device`, that is the folder of the loader build.
const KEPT: &str = "target/hot/picked-device";
/// Names the engine repo when it is not found above the app.
const ENGINE_ENV: &str = "HILEN_REPO";
const ENGINE_CRATE: &str = "hilen/Cargo.toml";
const TV_KIND: &str = "appleTV";
/// A started loader needs a moment until it answers.
const WAKE_TRIES: u32 = 20;
const WAKE_POLL: Duration = Duration::from_secs(1);
/// `hot-status` of a hot build names its library.
const HOT_MARK: &str = "library";
/// `build-time` of any app that answers the inspector starts with this.
const APP_MARK: &str = "app code built";
/// An app has to answer as no hot build this many times in a row before it
/// is taken for one, a loader in its start may answer in between.
const PLAIN_TRIES: u32 = 2;

/// What answers on a device after the start of the loader.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Woke {
    /// A hot build, it takes a library.
    Hot,
    /// An app that answers the inspector and is no hot build. No wait
    /// changes that, the loader has to be installed again. Once such an
    /// app sat on a phone and the send waited 90 seconds on it for nothing.
    Plain,
}

/// What the answers of the inspect tool say about the app in front,
/// nothing while it does not answer at all.
fn seen(status: &str, build_time: &str) -> Option<Woke> {
    if status.contains(HOT_MARK) {
        Some(Woke::Hot)
    } else if build_time.contains(APP_MARK) {
        Some(Woke::Plain)
    } else {
        None
    }
}

pub struct Device {
    /// The id every `devicectl` command takes.
    pub id:     String,
    pub name:   String,
    /// The system and its version, like `tvOS 26.3`.
    pub os:     String,
    pub system: System,
    /// An app on it answers the inspect tool.
    answers:    bool,
    inspect:    PathBuf,
}

impl Device {
    /// The paired device `word` names, by its id or by a part of its name or
    /// kind. With no word it is the only paired device. `here` is the
    /// engine repo, its inspect tool does the asking.
    pub fn pick(here: &Path, word: Option<&str>) -> Result<Self> {
        let inspect = inspect_tool(here)?;
        let flag = word.map(|word| format!(" --device \"{word}\"")).unwrap_or_default();
        let list = capture(&format!("\"{}\"{flag} devices", inspect.display()))?;
        let mut found = list.lines().map(|line| Self::from_line(line, &inspect)).collect::<Result<Vec<_>>>()?;
        match found.len() {
            1 => Ok(found.remove(0)),
            0 => bail!("no paired device, plug it in, unlock it and tap Trust"),
            _ => bail!("several paired devices, name 1 of them, like `make device args=tv`:\n{list}"),
        }
    }

    /// A line of `hilen-inspect devices`: the id, the kind, the name, the
    /// system with its version and the address an app answers at, with a
    /// tab between them.
    fn from_line(line: &str, inspect: &Path) -> Result<Self> {
        let parts: Vec<&str> = line.split('\t').collect();
        // An older tool prints no system, the address is always last.
        if parts.len() < 4 {
            bail!("`hilen-inspect devices` printed a line that is no device: {line}");
        }
        let (id, kind, name, addr) = (parts[0], parts[1], parts[2], parts[parts.len() - 1]);
        let os = if parts.len() > 4 { parts[3] } else { "" };
        Ok(Self {
            id:      id.to_string(),
            name:    name.to_string(),
            os:      os.to_string(),
            system:  if kind == TV_KIND { System::Tvos } else { System::Ios },
            answers: addr != "-",
            inspect: inspect.to_path_buf(),
        })
    }

    /// The shell line of an inspect command for this device.
    pub fn inspect(&self, command: &str) -> String {
        format!("\"{}\" --device {} {command}", self.inspect.display(), self.id)
    }

    fn ask(&self) -> Option<Woke> {
        let status = probe(&self.inspect("hot-status"));
        let build_time =
            if status.contains(HOT_MARK) { String::new() } else { probe(&self.inspect("build-time")) };
        seen(&status, &build_time)
    }

    /// Starts the loader `bundle_id` when no hot build answers on the
    /// device, and waits until one does.
    pub fn wake(&self, bundle_id: &str) -> Result<Woke> {
        if self.answers && self.ask() == Some(Woke::Hot) {
            return Ok(Woke::Hot);
        }
        println!("\n[device] no hot build answers on {}, starting the loader", self.name);
        run(&format!("xcrun devicectl device process launch --device {} --terminate-existing {bundle_id}", self.id))
            .with_context(|| {
                format!(
                    "the loader did not start on {}. Unlock the device. When the loader is not on it, install it with `make device args=install`",
                    self.name
                )
            })?;
        self.wait()
    }

    /// Waits until the loader that was just started answers.
    pub fn wait(&self) -> Result<Woke> {
        let mut plain = 0;
        for _ in 0..WAKE_TRIES {
            sleep(WAKE_POLL);
            match self.ask() {
                Some(Woke::Hot) => return Ok(Woke::Hot),
                Some(Woke::Plain) => {
                    plain += 1;
                    if plain == PLAIN_TRIES {
                        return Ok(Woke::Plain);
                    }
                }
                None => plain = 0,
            }
        }
        bail!("the loader on {} was started, but it does not answer. Keep the device unlocked with the loader in front", self.name)
    }
}

/// The engine repo on disk: the one `HILEN_REPO` names, the app itself, or
/// a folder `hilen` next to a folder above the app, like `~/dev/hilen` for
/// `~/dev/apps/game`.
fn engine_repo(app: &Path) -> Result<PathBuf> {
    if let Ok(named) = var(ENGINE_ENV) {
        let named = PathBuf::from(named);
        if named.join(ENGINE_CRATE).is_file() {
            return Ok(named);
        }
        bail!("{ENGINE_ENV} names {}, which has no {ENGINE_CRATE}", named.display());
    }
    if app.join(ENGINE_CRATE).is_file() {
        return Ok(app.to_path_buf());
    }
    app.ancestors()
        .skip(1)
        .map(|dir| dir.join("hilen"))
        .find(|dir| dir.join(ENGINE_CRATE).is_file())
        .with_context(|| {
            format!("no hilen repo found above {}, name it with {ENGINE_ENV}", app.display())
        })
}

/// `make device` in the repo `app`: sends the app to a paired device, or
/// with the `command` `install` or `status` works on the loader there.
/// `word` picks the device. With none it is the device of the last call,
/// or the only paired one.
pub fn make_device(app: &Path, word: Option<&str>, command: Option<&str>) -> Result<()> {
    let engine = engine_repo(app)?;
    let kept = app.join(KEPT);
    let word = match word {
        Some(word) => Some(word.to_string()),
        None => read_to_string(&kept).ok().map(|id| id.trim().to_string()),
    };

    // The loader is built from the engine repo, and so is the inspect tool.
    set_current_dir(&engine)?;
    let device = Device::pick(&engine, word.as_deref())?;
    println!("\n[device] {}, {}, {}", device.name, device.os, device.id);
    if let Some(dir) = kept.parent() {
        create_dir_all(dir)?;
    }
    write(&kept, &device.id)?;

    let swap = Swap::new(device.system)?;
    match command {
        Some("install") => swap.device_install(&device),
        Some("status") => swap.device_status(&device),
        _ if app == engine => swap.device_to(None, &device),
        _ => swap.device_to(Some(&app.display().to_string()), &device),
    }
}

#[cfg(test)]
mod tests {
    use std::{env::temp_dir, fs::remove_dir_all, process::id};

    use super::*;

    #[test]
    fn a_device_is_read_from_a_line_of_the_inspect_tool() -> Result<()> {
        let tool = Path::new("hilen-inspect");
        let phone = Device::from_line("1E96\tiPhone\tMy iPhone\tiOS 27.0.1\t[fd00::1]:7435", tool)?;
        assert_eq!(phone.id, "1E96");
        assert_eq!(phone.name, "My iPhone");
        assert_eq!(phone.os, "iOS 27.0.1");
        assert!(phone.system == System::Ios);
        assert!(phone.answers);

        let tv = Device::from_line("88F1\tappleTV\tBedroom TV\ttvOS 26.3\t-", tool)?;
        assert!(tv.system == System::Tvos);
        assert!(!tv.answers);

        assert!(Device::from_line("no tabs here", tool).is_err());
        Ok(())
    }

    #[test]
    fn an_app_that_answers_with_no_library_is_no_hot_build() {
        let hot = "loader   given at 192.168.0.208:7435\nlibrary  1791881864812.dylib";
        let none = "Error: No hot build answers on My iPhone.";
        let stamp = "app code built: 1791644213\napp started:    1791881508";
        let asleep = "Error: The app took the connection and gave no answer";

        assert_eq!(seen(hot, ""), Some(Woke::Hot));
        assert_eq!(seen(none, stamp), Some(Woke::Plain));
        assert_eq!(seen(none, asleep), None);
    }

    #[test]
    fn the_engine_repo_is_found_above_an_app() -> Result<()> {
        let dir = temp_dir().join(format!("hilen-device-test-{}", id()));
        let app = dir.join("apps/game");
        create_dir_all(&app)?;
        create_dir_all(dir.join("hilen/hilen"))?;
        write(dir.join("hilen").join(ENGINE_CRATE), "")?;

        assert_eq!(engine_repo(&app)?, dir.join("hilen"));
        assert_eq!(engine_repo(&dir.join("hilen"))?, dir.join("hilen"));
        remove_dir_all(&dir)?;
        Ok(())
    }
}
