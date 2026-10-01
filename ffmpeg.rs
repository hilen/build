#!/usr/bin/env rust

// Builds the static ffmpeg libraries hilen links for video playback, see
// docs/video.md in hilen. Run once per host. The archive in dist/ goes to a
// release of this repo and the forked ffmpeg-sys-next downloads it from there, so a
// normal build never compiles ffmpeg. The configure flags mirror what the
// ffmpeg-sys-next `build` feature passes, minus debug info, so a locally
// built archive and a downloaded one link the same way.

use anyhow::{Result, bail};
use sha2::{Digest, Sha256};
use shared::run::{capture, run};

const VERSION: &str = "9.0";
/// The software AV1 decoder, built here and packed into the archive. ffmpeg
/// has no AV1 decoder of its own that runs without a hardware one.
const DAV1D: &str = "1.5.4";

fn main() -> Result<()> {
    let triple = host_triple()?;
    let root = std::env::current_dir()?;
    let src = root.join("target/ffmpeg-src");
    let dist = root.join("target/ffmpeg-dist");
    let src_str = src.display().to_string();
    let dist_str = dist.display().to_string();

    if !src.join("configure").exists() {
        run(&format!(
            "git clone --depth=1 -b release/{VERSION} https://github.com/FFmpeg/FFmpeg {src_str}"
        ))?;
    }
    if dist.exists() {
        std::fs::remove_dir_all(&dist)?;
    }

    // dav1d first, into the same prefix, so ffmpeg finds it through
    // pkg-config and its static library lands next to the ffmpeg ones.
    let dav1d_src = root.join("target/dav1d-src");
    let dav1d_build = root.join("target/dav1d-build");
    let dav1d_src_str = dav1d_src.display().to_string();
    let dav1d_build_str = dav1d_build.display().to_string();
    if !dav1d_src.join("meson.build").exists() {
        run(&format!(
            "git clone --depth=1 -b {DAV1D} https://code.videolan.org/videolan/dav1d.git {dav1d_src_str}"
        ))?;
    }
    if dav1d_build.exists() {
        std::fs::remove_dir_all(&dav1d_build)?;
    }
    run(&format!(
        "meson setup {dav1d_build_str} {dav1d_src_str} --prefix={dist_str} --libdir=lib --default-library=static --buildtype=release -Denable_tools=false -Denable_tests=false"
    ))?;
    run(&format!("ninja -C {dav1d_build_str} install"))?;

    // Autodetect is off, so the system TLS is named here too. Without it the
    // archive has no https protocol.
    let hw = if cfg!(target_os = "macos") {
        "--enable-videotoolbox --enable-securetransport"
    } else if cfg!(target_os = "linux") {
        "--enable-vaapi"
    } else if cfg!(target_os = "windows") {
        "--enable-d3d11va"
    } else {
        bail!("no hardware decoder flag for this host");
    };

    let flags = [
        "--enable-static",
        "--disable-shared",
        "--enable-pic",
        "--disable-autodetect",
        "--disable-programs",
        "--disable-doc",
        "--disable-debug",
        "--enable-stripping",
        "--enable-pthreads",
        "--enable-avcodec",
        "--enable-avformat",
        "--enable-swresample",
        "--enable-swscale",
        "--disable-avdevice",
        // Only the filters the engine uses: atempo changes the speed of the
        // sound and keeps its pitch, the other 2 are the ends of its graph.
        "--enable-avfilter",
        "--disable-filters",
        "--enable-filter=atempo",
        "--enable-filter=abuffer",
        "--enable-filter=abuffersink",
        // zlib for files with compressed headers, dav1d for AV1 where the
        // hardware has no decoder.
        "--enable-zlib",
        "--enable-libdav1d",
        "--pkg-config-flags=--static",
        "--disable-gpl",
        "--disable-version3",
        "--disable-nonfree",
    ]
    .join(" ");

    run(&format!(
        "cd {src_str} && PKG_CONFIG_PATH={dist_str}/lib/pkgconfig ./configure --prefix={dist_str} {flags} {hw}"
    ))?;
    run(&format!("make -C {src_str} -j{} install", jobs()))?;

    // What the archive needs linked besides the ffmpeg libraries, one
    // `<kind>=<name>` per line. The forked ffmpeg-sys-next reads it.
    std::fs::write(dist.join("lib/link.txt"), "static=dav1d\ndylib=z\n")?;

    std::fs::create_dir_all("dist")?;
    let name = format!("ffmpeg-{VERSION}-{triple}");
    let archive = format!("dist/{name}.tar.gz");
    run(&format!(
        "tar -C {dist_str} --exclude=lib/pkgconfig -czf {archive} include lib"
    ))?;

    let bytes = std::fs::read(&archive)?;
    let sha = hex::encode(Sha256::digest(&bytes));
    std::fs::write(format!("dist/{name}.sha256"), format!("{sha}  {name}.tar.gz\n"))?;
    println!("{archive}");
    println!("{sha}");
    Ok(())
}

fn host_triple() -> Result<String> {
    let info = capture("rustc -vV")?;
    for line in info.lines() {
        if let Some(host) = line.strip_prefix("host: ") {
            return Ok(host.trim().to_string());
        }
    }
    bail!("rustc -vV printed no host line")
}

fn jobs() -> String {
    let count = if cfg!(target_os = "macos") {
        capture("sysctl -n hw.ncpu")
    } else {
        capture("nproc")
    };
    count.unwrap_or_else(|_| "4".to_string())
}
