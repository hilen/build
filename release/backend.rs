#!/usr/bin/env rust

// Publishes a release to a Gebling backend, the server of polyraiders.com. It
// takes files at /artifacts/<product>/<version>/<file> and puts a version live
// on /finalize once all 4 are there: the Windows installer, the Mac dmg, the
// Linux zip and a server zip. The product is the package name.
//
//   backend.rs windows|mac|linux   uploads what that platform's script built
//   backend.rs finalize            uploads the server zip, then finalizes
//
// A game without a server of its own ships the server zip of the release
// that is live now, so the session manager keeps running the old one.
// BACKEND_URL and RELEASE_UPLOAD_TOKEN come from the env.

use anyhow::{Context, Result, bail};
use serde::Deserialize;
use shared::release::{self, Release};
use shared::run::{capture, run};

/// The token stays a shell variable in the string, so no log shows its value.
const CURL: &str = r#"curl --fail --show-error --silent --retry 3 --retry-all-errors -H "Authorization: Bearer $RELEASE_UPLOAD_TOKEN""#;

#[derive(Deserialize)]
struct Latest {
    server_url: String,
}

fn main() -> Result<()> {
    let r = release::read()?;
    let backend = std::env::var("BACKEND_URL").context("BACKEND_URL")?;
    let backend = backend.trim_end_matches('/');
    if std::env::var("RELEASE_UPLOAD_TOKEN").is_err() {
        bail!("RELEASE_UPLOAD_TOKEN is not set");
    }
    let version = format!("v{}", r.version);
    let step = std::env::args().nth(1).unwrap_or_default();

    let file = match step.as_str() {
        "windows" => dist(&r, "windows-x64-setup.exe")?,
        "mac" => dist(&r, "mac-universal.dmg")?,
        "linux" => linux_zip(&r, &version)?,
        "finalize" => {
            let server = server_zip(backend, &r.name, &version)?;
            upload(backend, &r.name, &version, &server, "server")?;
            run(&format!("{CURL} -X POST {backend}/artifacts/{}/{version}/finalize", r.name))?;
            println!("{} {version} is live", r.name);
            return Ok(());
        }
        other => bail!("unknown step '{other}', use windows, mac, linux or finalize"),
    };
    upload(backend, &r.name, &version, &file, &step)
}

/// A file of dist/ that the platform script built, by its suffix.
fn dist(r: &Release, suffix: &str) -> Result<String> {
    let path = format!("dist/{}", r.artifact(suffix));
    if !std::path::Path::new(&path).is_file() {
        bail!("{path} is missing, run the release script of that platform first");
    }
    Ok(path)
}

/// The x64 binary alone in a zip, named like the app.
fn linux_zip(r: &Release, version: &str) -> Result<String> {
    let bare = dist(r, "linux-x86_64")?;
    let stage = "target/backend-stage";
    std::fs::create_dir_all(stage)?;
    let bin = format!("{stage}/{}", r.name);
    std::fs::copy(&bare, &bin)?;
    run(&format!("chmod +x {bin}"))?;
    let zip = format!("dist/{}-linux-{version}.zip", r.name);
    if std::path::Path::new(&zip).exists() {
        std::fs::remove_file(&zip)?;
    }
    run(&format!("zip -j {zip} {bin}"))?;
    Ok(zip)
}

/// Downloads the server zip of the live release into dist/.
fn server_zip(backend: &str, product: &str, version: &str) -> Result<String> {
    let json = capture(&format!("curl --fail --show-error --silent {backend}/releases/{product}/latest"))?;
    let latest: Latest = serde_json::from_str(&json)
        .context("the live release, a first release has no server zip to carry over")?;
    std::fs::create_dir_all("dist")?;
    let path = format!("dist/{product}-server-{version}.zip");
    run(&format!(
        "curl --fail --show-error --silent --retry 3 -o {path} {backend}{}",
        latest.server_url
    ))?;
    println!("carried over {} as {path}", latest.server_url);
    Ok(path)
}

/// `kind` picks the name the backend expects for the file.
fn upload(backend: &str, product: &str, version: &str, file: &str, kind: &str) -> Result<()> {
    let name = match kind {
        "windows" => format!("{product}-windows-{version}-installer.exe"),
        "mac" => format!("{product}-mac-{version}.dmg"),
        "linux" => format!("{product}-linux-{version}.zip"),
        "server" => format!("{product}-server-{version}.zip"),
        other => bail!("no backend name for '{other}'"),
    };
    run(&format!(
        "{CURL} --upload-file {file} {backend}/artifacts/{product}/{version}/{name}"
    ))?;
    println!("uploaded {file} as {name}");
    Ok(())
}
