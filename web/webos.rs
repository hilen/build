#!/usr/bin/env rust

// Builds an app for an LG webOS TV. The TV runs the app as a web page in a
// Chromium that never updates, 79 on a 2021 set, so the wasm is built for
// that browser and the start script trunk writes is rewritten for it. Then
// the app is packed. A hosted app is a small .ipk whose page sends the TV to
// the address the app is served from. A packaged app holds the whole dist
// and starts from the TV. `--dist` stops after the dist.
//
//   rust ./build/web/webos.rs [--dist]

use std::fs::{copy, create_dir_all, read_to_string, remove_dir_all, remove_file, write};

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

/// Chromium 79 of webOS lists WEBGL_compressed_texture_astc, but its object
/// has no getSupportedProfiles, which came later. wgpu calls it to choose the
/// ASTC features and the throw stops the app. An extension without the call
/// is LDR only. It runs before the app script, so it is the first in head.
const ASTC_PROFILES: &str = r#"<script>
(function () {
    var getExtension = WebGL2RenderingContext.prototype.getExtension;
    WebGL2RenderingContext.prototype.getExtension = function (name) {
        var extension = getExtension.call(this, name);
        if (name === "WEBGL_compressed_texture_astc" && extension && !extension.getSupportedProfiles) {
            extension.getSupportedProfiles = function () {
                return ["ldr"];
            };
        }
        return extension;
    };
})();
</script>"#;

/// The page trunk builds a packaged app from, made next to index.html for
/// the build and removed after it.
const PACKAGED_PAGE: &str = "webos.index.html";

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
    // The V8 of an LG C1 compiles wasm with its slow optimizing compiler
    // only, Liftoff is off. With it the 6 MB wasm of flixen started Rust
    // after 10 s in place of 17.7 s. Lazy compilation and more compile tasks
    // were measured too and gave nothing on top. The TV reads this key only
    // at install, an edit of the installed file does nothing.
    v8_extra_flags: String,
    // The TV shows it from the launch until the first frame, the compile of
    // the wasm is black otherwise.
    splash_background: String,
    // The launcher tile is taller than the icon and fills the rest with
    // black when this is missing, a square icon got black bars at the top
    // and the bottom on an LG C1.
    #[serde(skip_serializing_if = "Option::is_none")]
    icon_color: Option<String>,
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
    // A packaged app opens from a file:// address, where links that start at
    // `/` point at the root of the TV file system.
    let public_url = if webos.packaged { " --public-url ./" } else { "" };
    let page = if webos.packaged {
        packaged_page(webos)?
    } else {
        "index.html".to_string()
    };

    // The standard library is rebuilt with the same flags. `--no-sri` leaves
    // the integrity attributes out, the start script is changed after the
    // build and its hash would no longer hold. `deploy-wasm` is the shipping
    // profile with fat LTO. Without Liftoff the TV compiles wasm with its slow
    // optimizing compiler only, about 4.7 s a MB on an LG C1, and with it the
    // time still grows with the code, so the TV build alone is built for size. Measured there in flixen: opt-level 3 started Rust
    // after 37.4 s, "s" after 24.6 s, "z" after 20.2 s, at the same frame
    // times.
    let built = run(&format!(
        "cd \"{}\" && RUSTFLAGS=\"{tokio}{TARGET_FLAGS}\" CARGO_UNSTABLE_BUILD_STD=std,panic_abort \
         CARGO_PROFILE_DEPLOY_WASM_OPT_LEVEL=z \
         trunk build {page} --release --cargo-profile deploy-wasm --no-sri{public_url} --features {}{default_features}",
        webos.crate_dir, webos.features
    ));
    if webos.packaged {
        remove_file(format!("{}/{PACKAGED_PAGE}", webos.crate_dir))?;
    }
    built
}

/// A packaged app opens from a file, where Chromium 79 loads no module
/// script. Trunk builds it from a copy of index.html that asks wasm-bindgen
/// for a classic script, which keeps the bindings in a global `wasm_bindgen`.
fn packaged_page(webos: &Webos) -> Result<String> {
    let page = read_to_string(format!("{}/index.html", webos.crate_dir))?;
    let link = r#"data-trunk rel="rust""#;
    ensure!(
        page.matches(link).count() == 1,
        "index.html of {} needs exactly 1 <link {link}>",
        webos.crate_dir
    );
    let classic = page.replace(link, &format!(r#"{link} data-bindgen-target="no-modules""#));
    write(format!("{}/{PACKAGED_PAGE}", webos.crate_dir), classic)?;
    Ok(PACKAGED_PAGE.to_string())
}

/// The start script trunk writes uses a top level `await`, which came in
/// Chrome 89. Chromium 79 stops with `Unexpected reserved word`. The same
/// script with `then` runs everywhere.
fn fix_start_script(webos: &Webos) -> Result<()> {
    let path = format!("{}/dist/index.html", webos.crate_dir);
    let page = read_to_string(&path).with_context(|| format!("no {path} after the build"))?;

    let fixed = if webos.packaged {
        classic_start_script(webos, &page)?
    } else {
        without_top_level_await(&page)?
    };
    ensure!(
        !fixed.contains("await init("),
        "the start script of {path} still has a top level await"
    );
    ensure!(
        fixed.matches("<head>").count() == 1,
        "{path} needs exactly 1 <head> for the ASTC script"
    );
    let fixed = fixed.replace("<head>", &format!("<head>\n{ASTC_PROFILES}"));

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

/// The page of a packaged app loads the classic script and reads the wasm
/// by XHR. A file:// page on the TV can neither import a module nor fetch,
/// and the preload links would fetch too.
fn classic_start_script(webos: &Webos, page: &str) -> Result<String> {
    let script = Regex::new(
        r"(?s)<script type=.module.>\s*import init, \* as bindings from '\./([^']+\.js)';\s*const wasm = await init\(\{ module_or_path: '\./([^']+\.wasm)' \}\);.*?</script>",
    )?;
    let Some(found) = script.captures(page) else {
        bail!("the page has no trunk start script that imports init and bindings, trunk changed its template");
    };
    let js = found[1].to_string();
    let wasm = found[2].to_string();

    let code = read_to_string(format!("{}/dist/{js}", webos.crate_dir))?;
    ensure!(
        !code.contains("import.meta") && !code.lines().any(|line| line.starts_with("export ")),
        "{js} is still an ES module, the no-modules target of wasm-bindgen did not apply"
    );

    let start = format!(
        r#"<script src="./{js}"></script>
<script>
(function () {{
    var request = new XMLHttpRequest();
    request.open("GET", "./{wasm}");
    request.responseType = "arraybuffer";
    request.onloadend = function () {{
        if (!request.response) {{
            console.error("Failed to read ./{wasm}");
            return;
        }}
        wasm_bindgen({{ module_or_path: request.response }}).then(function (wasm) {{
            window.wasmBindings = wasm_bindgen;
            dispatchEvent(new CustomEvent("TrunkApplicationStarted", {{ detail: {{ wasm: wasm }} }}));
        }});
    }};
    request.send();
}})();
</script>"#
    );
    let preload = Regex::new(r#"<link rel="(modulepreload|preload)" [^>]*>\n?"#)?;
    let page = script.replace(page, start.as_str()).into_owned();
    Ok(preload.replace_all(&page, "").into_owned())
}

fn pack(webos: &Webos) -> Result<()> {
    let url = match (&webos.url, webos.packaged) {
        (_, true) => None,
        (Some(url), false) => Some(url),
        (None, false) => bail!(
            "hilen.toml has no url in its [webos] table, the hosted app needs the address it loads"
        ),
    };
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
    let icon_color = icon_color(&webos.icon)?;
    splash(&webos.icon, &format!("{dir}/splash.png"), icon_color.as_deref().unwrap_or("#ffffff"))?;

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
        v8_extra_flags: "--liftoff".to_string(),
        splash_background: "splash.png".to_string(),
        icon_color,
    };
    write(format!("{dir}/appinfo.json"), serde_json::to_string_pretty(&info)?)?;
    match url {
        Some(url) => write(format!("{dir}/index.html"), launcher_page(&webos.title, url)?)?,
        None => run(&format!("cp -R \"{}/dist/.\" \"{dir}/\"", webos.crate_dir))?,
    }

    // The folder is whole before this check, so a machine with the packer
    // can pack the folder of a builder that has none.
    ensure!(
        !probe("command -v ares-package").trim().is_empty(),
        "ares-package is not installed, run: npm install -g @webos-tools/cli. The folder to pack is {dir}"
    );
    create_dir_all("dist")?;
    // The minifier of the tool chokes on new JavaScript, and trunk already
    // minified the dist of a packaged app.
    run(&format!("ares-package --no-minify \"{dir}\" -o dist"))?;

    let start = url.map_or_else(
        || "it holds the whole app".to_string(),
        |url| format!("it loads {url}"),
    );
    println!(
        "packed dist/{}_{}_all.ipk, {start}. Install it with: ares-install dist/{}_{}_all.ipk",
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

/// The color of the top left pixel of the icon, the background of the tile
/// around it. None when that pixel is transparent.
fn icon_color(source: &str) -> Result<Option<String>> {
    if !probe("command -v sips").trim().is_empty() {
        let bmp = "target/webos/icon-color.bmp";
        run(&format!("sips -s format bmp \"{source}\" --out {bmp} >/dev/null"))?;
        let bytes = std::fs::read(bmp)?;
        remove_file(bmp)?;
        return Ok(bmp_top_left(&bytes)?.map(|[red, green, blue]| format!("#{red:02x}{green:02x}{blue:02x}")));
    }
    if !probe("command -v magick").trim().is_empty() {
        let pixel = probe(&format!("magick \"{source}\" -format '%[hex:p{{0,0}}]' info:"));
        let pixel = pixel.trim();
        ensure!(pixel.len() >= 6, "magick gave no pixel for {source}: {pixel}");
        let transparent = pixel.len() == 8 && pixel.ends_with("00");
        return Ok((!transparent).then(|| format!("#{}", pixel[..6].to_lowercase())));
    }
    bail!("no sips and no magick to read the icon color, install ImageMagick")
}

/// The top left pixel of a 24 or 32 bit BMP as red, green and blue. A BMP
/// keeps its rows from the bottom up unless its height is negative.
fn bmp_top_left(bytes: &[u8]) -> Result<Option<[u8; 3]>> {
    let u32_at = |at: usize| u32::from_le_bytes([bytes[at], bytes[at + 1], bytes[at + 2], bytes[at + 3]]);
    ensure!(bytes.len() > 54 && &bytes[..2] == b"BM", "not a BMP");
    let data = u32_at(10) as usize;
    let width = u32_at(18) as usize;
    let height = u32_at(22) as i32;
    let depth = u16::from_le_bytes([bytes[28], bytes[29]]) as usize;
    ensure!(depth == 24 || depth == 32, "a BMP of {depth} bits");
    let row = (width * depth / 8).div_ceil(4) * 4;
    let top = if height < 0 { 0 } else { (height as usize - 1) * row };
    let at = data + top;
    let alpha = if depth == 32 { bytes[at + 3] } else { 255 };
    Ok((alpha > 0).then(|| [bytes[at + 2], bytes[at + 1], bytes[at]]))
}

/// The icon in the middle of a screen of the TV, 1920 by 1080, filled with
/// the background color of the icon so its edge does not show.
fn splash(source: &str, target: &str, color: &str) -> Result<()> {
    if !probe("command -v sips").trim().is_empty() {
        copy(source, target)?;
        let pad = color.trim_start_matches('#');
        return run(&format!(
            "sips -z 320 320 \"{target}\" >/dev/null && sips --padToHeightWidth 1080 1920 --padColor {pad} \"{target}\" >/dev/null"
        ));
    }
    if !probe("command -v magick").trim().is_empty() {
        return run(&format!(
            "magick -size 1920x1080 \"xc:{color}\" \\( \"{source}\" -resize 320x320 \\) -gravity center -composite \"{target}\""
        ));
    }
    bail!("no sips and no magick to make the splash, install ImageMagick")
}
