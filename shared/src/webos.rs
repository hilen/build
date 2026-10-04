//! What the LG webOS build needs. The package comes from project_name in
//! hilen.toml, its folder and version from cargo metadata, the rest from
//! the `[webos]` table of hilen.toml:
//!
//! ```toml
//! [webos]
//! url = "https://myapp.example.com"   # where the TV loads the app from
//! title = "My App"                    # the name on the TV, project_name when left out
//! icon = "assets/icon.png"            # a square png, this path when left out
//! features = "webgl"                  # cargo features of the build, this when left out
//! default_features = true             # false leaves the default features out
//! ```

use std::{fs::read_to_string, path::Path};

use anyhow::{Context, Result};
use serde::Deserialize;

use crate::{config, run::capture};

pub struct Webos {
    /// cargo package name
    pub name: String,
    /// the folder of the app crate, where trunk runs and `dist` lands
    pub crate_dir: String,
    pub version: String,
    /// the webOS app id, the bundle id in lower case
    pub id: String,
    pub title: String,
    /// The address the packaged app loads. Without it only the dist is built.
    pub url: Option<String>,
    pub icon: String,
    pub features: String,
    pub default_features: bool,
}

#[derive(Deserialize, Default)]
struct Hilen {
    #[serde(default)]
    webos: Table,
}

#[derive(Deserialize, Default)]
struct Table {
    url: Option<String>,
    title: Option<String>,
    icon: Option<String>,
    features: Option<String>,
    default_features: Option<bool>,
}

#[derive(Deserialize)]
struct Metadata {
    packages: Vec<Package>,
}

#[derive(Deserialize)]
struct Package {
    name: String,
    version: String,
    manifest_path: String,
}

/// Read from the repo root, before any chdir.
pub fn read() -> Result<Webos> {
    let config = config::read()?;
    let hilen: Hilen =
        toml::from_str(&read_to_string("hilen.toml")?).context("[webos] table in hilen.toml")?;

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
    let crate_dir = Path::new(&package.manifest_path)
        .parent()
        .context("the package manifest has no folder")?
        .to_string_lossy()
        .into_owned();

    let table = hilen.webos;
    Ok(Webos {
        title: table.title.unwrap_or_else(|| config.project_name.clone()),
        id: config.bundle_id.to_lowercase(),
        url: table.url.map(|url| url.trim_end_matches('/').to_string()),
        icon: table.icon.unwrap_or_else(|| "assets/icon.png".to_string()),
        features: table.features.unwrap_or_else(|| "webgl".to_string()),
        default_features: table.default_features.unwrap_or(true),
        name: package.name,
        version: package.version,
        crate_dir,
    })
}
