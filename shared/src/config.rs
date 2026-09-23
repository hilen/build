//! The single source for project naming. hilen-mobile reads the same
//! hilen.toml when it generates the mobile projects and derives the same
//! casings from project_name, so these must match what it produces or the paths
//! the generated Xcode project uses will not line up.

use anyhow::{Context, Result};

pub struct Config {
    /// cargo package name, and the Android lib name
    pub app_name: String,
    /// Xcode project, scheme and target name
    pub project_name: String,
    /// the staticlib cargo lipo produces, which the Xcode project links
    pub lib_name: String,
    pub bundle_id: String,
    /// CFBundleShortVersionString for the iOS build. hilen-mobile bakes 1.0 into
    /// the generated Info.plist with no knob, so the build patches it from this
    /// value. The App Store rejects an upload whose version is not higher than
    /// the live one.
    pub version: String,
    /// Minimum iOS version written into every generated Xcode configuration.
    pub ios_minimum_version: String,
}

/// Read from the repo root. Several scripts chdir into mobile/iOS partway
/// through, so read this before that happens, not lazily after.
pub fn read() -> Result<Config> {
    let text = std::fs::read_to_string("hilen.toml")
        .context("hilen.toml not found, run this from the repo root")?;
    let value: serde_json::Value = toml::from_str(&text)?;

    let project = value
        .get("project_name")
        .context("project_name not found in hilen.toml")?
        .as_str()
        .unwrap_or_default();
    let bundle_id = value
        .get("bundle_id")
        .context("bundle_id not found in hilen.toml")?
        .as_str()
        .unwrap_or_default();
    let version = value
        .get("version")
        .and_then(|v| v.as_str())
        .unwrap_or("1.0");
    let ios_minimum_version = value
        .get("ios_minimum_version")
        .and_then(|v| v.as_str())
        .unwrap_or("12.0");

    let parts = words(project);
    let snake = parts.join("_");

    Ok(Config {
        app_name: parts.join("-"),
        project_name: parts.iter().map(|w| capitalize(w)).collect::<String>(),
        lib_name: format!("lib{snake}.a"),
        bundle_id: bundle_id.to_string(),
        version: version.to_string(),
        ios_minimum_version: ios_minimum_version.to_string(),
    })
}

/// Split a name into lowercase words on dashes, underscores and camel humps, so
/// the casing works whatever style hilen.toml uses.
fn words(name: &str) -> Vec<String> {
    let mut spaced = String::new();
    let mut previous_lower = false;
    for c in name.chars() {
        if c.is_ascii_uppercase() && previous_lower {
            spaced.push(' ');
        }
        previous_lower = c.is_ascii_lowercase() || c.is_ascii_digit();
        spaced.push(c);
    }
    spaced
        .split(['-', '_', ' '])
        .filter(|w| !w.is_empty())
        .map(str::to_lowercase)
        .collect()
}

fn capitalize(word: &str) -> String {
    let mut chars = word.chars();
    match chars.next() {
        Some(first) => first.to_ascii_uppercase().to_string() + chars.as_str(),
        None => String::new(),
    }
}
