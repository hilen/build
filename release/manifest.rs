#!/usr/bin/env rust

// Emits dist/manifest.json for the website and dist/updater.json for the
// engine updater. Presence comes from dist/ by default, or from a file
// listing the names on the download host with `--present <file>`, the CI
// case where only the .meta.json sidecars were pulled back to the runner.

use std::collections::BTreeMap;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use shared::release::{self, Release};

#[derive(Deserialize, Serialize, Clone)]
struct Meta {
    size: u64,
    sha256: String,
    sig: String,
}

#[derive(Serialize)]
struct Platform {
    url: String,
    size: u64,
    sha256: String,
    sig: String,
}

#[derive(Serialize)]
struct UpdaterManifest {
    version: String,
    notes: String,
    platforms: BTreeMap<String, Platform>,
}

#[derive(Serialize)]
struct Arches {
    #[serde(skip_serializing_if = "Option::is_none")]
    x64: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    arm64: Option<String>,
}

#[derive(Serialize)]
struct LinuxArch {
    #[serde(skip_serializing_if = "Option::is_none")]
    deb: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    appimage: Option<String>,
}

#[derive(Serialize)]
struct Linux {
    x64: LinuxArch,
    arm64: LinuxArch,
}

#[derive(Serialize)]
struct SiteManifest {
    version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    mac: Option<String>,
    win: Arches,
    linux: Linux,
}

fn main() -> Result<()> {
    let r = release::read()?;
    let args: Vec<String> = std::env::args().skip(1).collect();
    let present: Vec<String> = match args.iter().position(|a| a == "--present") {
        Some(i) => {
            let file = args.get(i + 1).context("--present needs a file")?;
            std::fs::read_to_string(file)?
                .lines()
                .map(|l| l.trim().to_string())
                .filter(|l| !l.is_empty())
                .collect()
        }
        None => std::fs::read_dir("dist")?
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .collect(),
    };
    let has = |suffix: &str| -> Option<String> {
        let name = r.artifact(suffix);
        present.contains(&name).then_some(name)
    };

    let site = SiteManifest {
        version: r.version.clone(),
        mac: has("mac-universal.dmg"),
        win: Arches {
            x64: has("windows-x64-setup.exe"),
            arm64: has("windows-arm64-setup.exe"),
        },
        linux: Linux {
            x64: LinuxArch {
                deb: has("linux-x64.deb"),
                appimage: has("linux-x64.AppImage"),
            },
            arm64: LinuxArch {
                deb: has("linux-aarch64.deb"),
                appimage: has("linux-aarch64.AppImage"),
            },
        },
    };
    let text = serde_json::to_string_pretty(&site)?;
    std::fs::write("dist/manifest.json", format!("{text}\n"))?;
    println!("{text}");

    let updater = updater_manifest(&r, &has)?;
    if updater.platforms.is_empty() {
        eprintln!("warn: no signed update artifacts, skipping updater.json");
        return Ok(());
    }
    let text = serde_json::to_string_pretty(&updater)?;
    std::fs::write("dist/updater.json", format!("{text}\n"))?;
    println!("{text}");
    Ok(())
}

// The universal mac binary serves both mac keys. Linux gets the bare
// binary and the AppImage under its own key, the engine picks by how
// the app runs. A deb install in /usr/bin is not user writable, the
// engine offers it no update, those users update through apt.
fn updater_manifest(r: &Release, has: &dyn Fn(&str) -> Option<String>) -> Result<UpdaterManifest> {
    let mut platforms = BTreeMap::new();
    let entries = [
        ("macos-aarch64", "macos-universal"),
        ("macos-x86_64", "macos-universal"),
        ("windows-x86_64", "windows-x64.exe"),
        ("windows-aarch64", "windows-arm64.exe"),
        ("linux-x86_64", "linux-x86_64"),
        ("linux-aarch64", "linux-aarch64"),
        ("linux-x86_64-appimage", "linux-x64.AppImage"),
        ("linux-aarch64-appimage", "linux-aarch64.AppImage"),
    ];
    for (key, suffix) in entries {
        let Some(name) = has(suffix) else { continue };
        let meta_path = format!("dist/{name}.meta.json");
        let Ok(text) = std::fs::read_to_string(&meta_path) else {
            eprintln!("warn: {meta_path} missing, {key} left out of updater.json");
            continue;
        };
        let meta: Meta = serde_json::from_str(&text)?;
        platforms.insert(
            key.to_string(),
            Platform {
                url: format!("{}/{name}", r.download_url()?),
                size: meta.size,
                sha256: meta.sha256,
                sig: meta.sig,
            },
        );
    }
    Ok(UpdaterManifest {
        version: r.version.clone(),
        notes: String::new(),
        platforms,
    })
}
