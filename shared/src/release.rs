//! What the desktop release scripts need. The package comes from project_name
//! in hilen.toml, its version and binary name from cargo metadata, the rest
//! from the `[release]` table of hilen.toml. Asking cargo keeps this right for
//! a workspace, where the version sits in `[workspace.package]` and the window
//! app binary can carry another name than its package.

use std::fs::read_to_string;

use anyhow::{Context, Result, bail};
use serde::Deserialize;

use crate::{
    config,
    run::{capture, run},
};

pub struct Release {
    /// cargo package name, the artifact file name prefix
    pub name: String,
    /// the binary target of that package, the file name cargo builds
    pub bin: String,
    pub version: String,
    pub bundle_id: String,
    /// where the binaries are served, no trailing slash
    pub download_url: String,
    /// the beekeeper deployment whose data/download/ holds the binaries
    pub host_deployment: String,
    /// subdirectory under that data/download/
    pub target_subdir: String,
    /// the targets of the mac build, more than 1 is glued into a universal binary
    pub mac_targets: Vec<String>,
    /// false for an app without the engine updater, its binaries are not signed
    pub self_update: bool,
    /// the daemons of the app, each a bare signed binary per platform
    pub daemons: Vec<Daemon>,
}

/// A second product of an app, a binary with no window that updates itself
/// with `hilen-updater`, like a daemon. It ships as 1 signed bare binary per
/// platform, no bundle, no installer, with its own manifest next to the
/// app's. Named in `daemons` of the `[release]` table by its package name.
pub struct Daemon {
    /// cargo package name, the artifact file name prefix
    pub name: String,
    /// the binary target of that package, the file name cargo builds
    pub bin: String,
    pub version: String,
}

impl Daemon {
    /// `banda-daemon-0.2.0-macos-universal` style names.
    pub fn artifact(&self, suffix: &str) -> String {
        format!("{}-{}-{suffix}", self.name, self.version)
    }

    /// The manifest file of this daemon, `<name>-updater.json` next to the
    /// `updater.json` of the app.
    pub fn manifest(&self) -> String {
        format!("{}-updater.json", self.name)
    }
}

impl Release {
    /// `kukareker-0.2.0-mac-universal.dmg` style names.
    pub fn artifact(&self, suffix: &str) -> String {
        format!("{}-{}-{suffix}", self.name, self.version)
    }

    /// The word for the mac build in an artifact name, `universal` for the 2
    /// targets together, else the cpu of the 1 target.
    pub fn mac_arch(&self) -> Result<&'static str> {
        match self.mac_targets.iter().map(String::as_str).collect::<Vec<_>>().as_slice() {
            [_, _] => Ok("universal"),
            ["aarch64-apple-darwin"] => Ok("arm64"),
            ["x86_64-apple-darwin"] => Ok("x64"),
            other => bail!("mac_targets in hilen.toml must name 1 or 2 mac targets, got {other:?}"),
        }
    }

    /// Signs `files` for the updater, nothing for an app without it.
    pub fn sign(&self, files: &[&str]) -> Result<()> {
        if !self.self_update {
            return Ok(());
        }
        run(&format!("rust build/release/sign.rs {}", files.join(" ")))
    }
}

#[derive(Deserialize)]
struct Hilen {
    release: Distribution,
}

/// Every field can be left out. The download host fields then point at the
/// central download server, the `get` deployment, with the app name as the
/// folder. An app that still ships from another deployment names it here.
#[derive(Deserialize)]
struct Distribution {
    download_url: Option<String>,
    host_deployment: Option<String>,
    target_subdir: Option<String>,
    #[serde(default = "yes")]
    self_update: bool,
    #[serde(default = "universal")]
    mac_targets: Vec<String>,
    #[serde(default)]
    daemons: Vec<String>,
}

const DOWNLOAD_HOST: &str = "https://get.vladas.xyz";
const DOWNLOAD_DEPLOYMENT: &str = "get";

fn universal() -> Vec<String> {
    vec!["aarch64-apple-darwin".to_string(), "x86_64-apple-darwin".to_string()]
}

fn yes() -> bool {
    true
}

#[derive(Deserialize)]
struct Metadata {
    packages: Vec<Package>,
}

#[derive(Deserialize)]
struct Package {
    name: String,
    version: String,
    targets: Vec<Target>,
}

#[derive(Deserialize)]
struct Target {
    name: String,
    kind: Vec<String>,
}

/// Read from the repo root, before any chdir.
pub fn read() -> Result<Release> {
    let config = config::read()?;
    let hilen: Hilen =
        toml::from_str(&read_to_string("hilen.toml")?).context("[release] table in hilen.toml")?;

    let metadata: Metadata =
        serde_json::from_str(&capture("cargo metadata --no-deps --format-version 1")?)?;
    let release = hilen.release;
    let daemons = release
        .daemons
        .iter()
        .map(|name| {
            let package = find_package(&metadata.packages, name)
                .with_context(|| format!("no cargo package named {name}, listed in daemons of hilen.toml"))?;
            Ok(Daemon {
                name: package.name.clone(),
                bin: pick_bin(package)?,
                version: package.version.clone(),
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let package = find_package(&metadata.packages, &config.app_name).with_context(|| {
        format!(
            "no cargo package named {}, the project_name of hilen.toml",
            config.app_name
        )
    })?;
    let bin = pick_bin(package)?;
    let name = package.name.clone();
    let version = package.version.clone();

    Ok(Release {
        daemons,
        download_url: release.download_url.map_or_else(
            || format!("{DOWNLOAD_HOST}/{name}"),
            |url| url.trim_end_matches('/').to_string(),
        ),
        host_deployment: release.host_deployment.unwrap_or_else(|| DOWNLOAD_DEPLOYMENT.to_string()),
        target_subdir: release.target_subdir.unwrap_or_else(|| name.clone()),
        self_update: release.self_update,
        mac_targets: release.mac_targets,
        name,
        bin,
        version,
        bundle_id: config.bundle_id,
    })
}

fn find_package<'a>(packages: &'a [Package], name: &str) -> Option<&'a Package> {
    packages.iter().find(|p| p.name == name)
}

/// A binary named like the package is the one to ship, side binaries such
/// as a gallery are ignored. A lone binary under another name is it too, a
/// workspace needs that when another crate owns the package name.
fn pick_bin(package: &Package) -> Result<String> {
    let bins: Vec<&str> = package
        .targets
        .iter()
        .filter(|t| t.kind.iter().any(|k| k == "bin"))
        .map(|t| t.name.as_str())
        .collect();
    if bins.contains(&package.name.as_str()) {
        Ok(package.name.clone())
    } else if let [only] = bins.as_slice() {
        Ok((*only).to_string())
    } else {
        bail!(
            "cannot pick the binary of package {} to release, it has {}: {}",
            package.name,
            bins.len(),
            bins.join(", ")
        )
    }
}
