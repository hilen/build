#!/usr/bin/env rust

// Builds an app for an LG webOS TV. The TV runs the app as a web page in a
// Chromium that never updates, 79 on a 2021 set, so the wasm is built for
// that browser and the start script trunk writes is rewritten for it. Then
// the hosted app is packed: a small .ipk whose page sends the TV to the
// address the app is served from. `--dist` stops after the dist.
//
//   rust ./build/web/webos.rs [--dist]

use std::fs::{copy, create_dir_all, read_to_string, remove_dir_all, write};

use anyhow::{Context, Result, bail, ensure};
use regex::Regex;
use serde::Serialize;
use shared::{
    run::{probe, run},
    webos::{self, Webos},
};

// Chromium 79 knows only part of the wasm features a default Rust build
// turns on. It has no multivalue, no reference types and no BigInt at the
// JS border, so the build drops to the mvp cpu and turns these 4 back on.
const TARGET_FLAGS: &str =
    "-Ctarget-cpu=mvp -Ctarget-feature=+mutable-globals,+sign-ext,+nontrapping-fptoint,+bulk-memory";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct AppInfo {
    id: String,
    version: String,
    vendor: String,
    r#type: String,
    main: String,
    title: String,
    icon: String,
    large_icon: String,
    // The Back key reaches the page as key code 461 instead of moving the
    // browser history, the engine hands it on as Escape.
    #[serde(rename = "disableBackHistoryAPI")]
    disable_back_history_api: bool,
    // The app calls no Luna API of the TV. The packer asks for the list
    // also when it is empty.
    #[serde(rename = "requiredACG")]
    required_acg: Vec<String>,
}

fn main() -> Result<()> {
    let webos = webos::read()?;
    let dist_only = std::env::args().any(|arg| arg == "--dist");

    build_dist(&webos)?;
    fix_start_script(&webos)?;

    if dist_only {
        println!("the dist for the TV is in {}/dist", webos.crate_dir);
        return Ok(());
    }

    pack(&webos)
}

fn build_dist(webos: &Webos) -> Result<()> {
    run("rustup target add wasm32-unknown-unknown")?;
    run("rustup component add rust-src")?;
    run("command -v trunk >/dev/null || cargo install --locked trunk")?;

    // RUSTFLAGS in the environment replaces the rustflags of the cargo
    // config, so a cfg the project sets there has to be said again.
    let config = read_to_string(".cargo/config.toml").unwrap_or_default();
    let tokio = if config.contains("tokio_unstable") {
        "--cfg tokio_unstable "
    } else {
        ""
    };
    let default_features = if webos.default_features {
        ""
    } else {
        " --no-default-features"
    };

    // The standard library is rebuilt with the same flags. `--no-sri` leaves
    // the integrity attributes out, the start script is changed after the
    // build and its hash would no longer hold.
    run(&format!(
        "cd \"{}\" && RUSTFLAGS=\"{tokio}{TARGET_FLAGS}\" CARGO_UNSTABLE_BUILD_STD=std,panic_abort \
         trunk build --release --no-sri --features {}{default_features}",
        webos.crate_dir, webos.features
    ))
}

/// The start script trunk writes uses a top level `await`, which came in
/// Chrome 89. Chromium 79 stops with `Unexpected reserved word`. The same
/// script with `then` runs everywhere.
fn fix_start_script(webos: &Webos) -> Result<()> {
    let path = format!("{}/dist/index.html", webos.crate_dir);
    let page = read_to_string(&path).with_context(|| format!("no {path} after the build"))?;

    let fixed = without_top_level_await(&page)?;
    ensure!(
        !fixed.contains("await init("),
        "the start script of {path} still has a top level await"
    );

    write(&path, fixed)?;
    println!("start script of {path} rewritten for Chromium 79");
    Ok(())
}

fn without_top_level_await(page: &str) -> Result<String> {
    let script = Regex::new(r"(?s)const wasm = await init\((.*?)\);(.*?)</script>")?;
    ensure!(
        script.is_match(page),
        "the page has no trunk start script with `const wasm = await init(...)`, trunk changed its template"
    );
    Ok(script
        .replace(page, "init($1).then(function (wasm) {$2});\n</script>")
        .into_owned())
}

fn pack(webos: &Webos) -> Result<()> {
    let Some(url) = &webos.url else {
        bail!("hilen.toml has no url in its [webos] table, the packaged app needs the address it loads");
    };
    ensure!(
        !probe("command -v ares-package").trim().is_empty(),
        "ares-package is not installed, run: npm install -g @webos-tools/cli"
    );
    ensure!(
        std::path::Path::new(&webos.icon).exists(),
        "no icon at {}, set icon in the [webos] table of hilen.toml",
        webos.icon
    );

    let dir = format!("target/webos/{}", webos.name);
    if std::path::Path::new(&dir).exists() {
        remove_dir_all(&dir)?;
    }
    create_dir_all(&dir)?;

    icon(&webos.icon, &format!("{dir}/icon.png"), 80)?;
    icon(&webos.icon, &format!("{dir}/largeIcon.png"), 130)?;

    let info = AppInfo {
        id: webos.id.clone(),
        version: webos.version.clone(),
        vendor: webos.title.clone(),
        r#type: "web".to_string(),
        main: "index.html".to_string(),
        title: webos.title.clone(),
        icon: "icon.png".to_string(),
        large_icon: "largeIcon.png".to_string(),
        disable_back_history_api: true,
        required_acg: Vec::new(),
    };
    write(format!("{dir}/appinfo.json"), serde_json::to_string_pretty(&info)?)?;
    write(format!("{dir}/index.html"), launcher_page(&webos.title, url)?)?;

    create_dir_all("dist")?;
    // The page is 1 line of script, there is nothing to minify, and the
    // minifier of the tool chokes on new JavaScript.
    run(&format!("ares-package --no-minify \"{dir}\" -o dist"))?;

    println!(
        "packed dist/{}_{}_all.ipk, it loads {url}. Install it with: ares-install dist/{}_{}_all.ipk",
        webos.id, webos.version, webos.id, webos.version
    );
    Ok(())
}

/// The page inside the package. It only sends the TV on to the served app,
/// so the app on the TV is always the one the server has.
fn launcher_page(title: &str, url: &str) -> Result<String> {
    let address = serde_json::to_string(url)?;
    Ok(format!(
        r#"<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>body {{ margin: 0; background: #000; }}</style>
</head>
<body>
<script>window.location.replace({address});</script>
</body>
</html>
"#
    ))
}

/// A square copy of the icon with this side, with the tool the system has.
fn icon(source: &str, target: &str, side: u32) -> Result<()> {
    if !probe("command -v sips").trim().is_empty() {
        copy(source, target)?;
        return run(&format!("sips -z {side} {side} \"{target}\" >/dev/null"));
    }
    if !probe("command -v magick").trim().is_empty() {
        return run(&format!("magick \"{source}\" -resize {side}x{side} \"{target}\""));
    }
    bail!("no sips and no magick to scale the icon, install ImageMagick")
}
