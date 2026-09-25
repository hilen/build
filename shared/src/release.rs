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
    pub download_url: Option<String>,
    /// the beekeeper deployment whose data/download/ holds the binaries
    pub host_deployment: Option<String>,
    /// subdirectory under that data/download/
    pub target_subdir: Option<String>,
    /// false for an app without the engine updater, its binaries are not signed
    pub self_update: bool,
}

impl Release {
    /// `kukareker-0.2.0-mac-universal.dmg` style names.
    pub fn artifact(&self, suffix: &str) -> String {
        format!("{}-{}-{suffix}", self.name, self.version)
    }

    pub fn download_url(&self) -> Result<&str> {
        self.download_url.as_deref().context("download_url in the [release] table of hilen.toml")
    }

    pub fn host_deployment(&self) -> Result<&str> {
        self.host_deployment
            .as_deref()
            .context("host_deployment in the [release] table of hilen.toml")
    }

    pub fn target_subdir(&self) -> Result<&str> {
        self.target_subdir.as_deref().context("target_subdir in the [release] table of hilen.toml")
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

/// The download host fields are for apps served from a beekeeper
/// deployment. An app shipped some other way, like a game uploaded to its own
/// backend, leaves them out.
#[derive(Deserialize)]
struct Distribution {
    download_url: Option<String>,
    host_deployment: Option<String>,
    target_subdir: Option<String>,
    #[serde(default = "yes")]
    self_update: bool,
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
    let package = metadata
        .packages
        .into_iter()
        .find(|p| p.name == config.app_name)
        .with_context(|| {
            format!(
                "no cargo package named {}, the project_name of hilen.toml",
                config.app_name
            )
        })?;
    let bins: Vec<String> = package
        .targets
        .into_iter()
        .filter(|t| t.kind.iter().any(|k| k == "bin"))
        .map(|t| t.name)
        .collect();
    // A binary named like the package is the app, side binaries such as a
    // gallery are ignored. A lone binary under another name is the app too,
    // a workspace needs that when another crate owns the package name.
    let bin = if bins.contains(&package.name) {
        package.name.clone()
    } else if bins.len() == 1 {
        bins[0].clone()
    } else {
        bail!(
            "cannot pick the binary of package {} to release, it has {}: {}",
            package.name,
            bins.len(),
            bins.join(", ")
        );
    };

    Ok(Release {
        name: package.name,
        bin,
        version: package.version,
        bundle_id: config.bundle_id,
        download_url: hilen
            .release
            .download_url
            .map(|url| url.trim_end_matches('/').to_string()),
        host_deployment: hilen.release.host_deployment,
        target_subdir: hilen.release.target_subdir,
        self_update: hilen.release.self_update,
    })
}
