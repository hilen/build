#!/usr/bin/env rust

// Builds the static ffmpeg libraries hilen links for video playback, see
// docs/video.md in hilen. Run once per target. With no argument it builds
// for the host. On a Mac `aarch64-apple-ios` cross builds for an iPhone,
// `x86_64-apple-ios` for the simulator and `aarch64-apple-ios-sim` for the
// simulator of an Apple Silicon Mac, `aarch64-apple-tvos` for an Apple TV
// and `aarch64-apple-tvos-sim` for its simulator. The archive in dist/ goes to a
// release of this repo and the forked ffmpeg-sys-next downloads it from there, so a
// normal build never compiles ffmpeg. The configure flags mirror what the
// ffmpeg-sys-next `build` feature passes, minus debug info, so a locally
// built archive and a downloaded one link the same way.

use std::path::Path;

use anyhow::{Result, bail};
use sha2::{Digest, Sha256};
use shared::run::{capture, run};

const VERSION: &str = "9.0";
/// The software AV1 decoder, built here and packed into the archive. ffmpeg
/// has no AV1 decoder of its own that runs without a hardware one.
const DAV1D: &str = "1.5.4";
/// The oldest iOS the engine runs on, see docs/ios.md in hilen.
const IOS_MINIMUM: &str = "12.0";
/// The oldest tvOS, the default of `tvos_minimum_version` in hilen.toml.
const TVOS_MINIMUM: &str = "15.0";

/// What a cross build for an Apple device needs to know.
struct Cross {
    /// The name ffmpeg and clang have for the processor.
    arch:        &'static str,
    /// The name meson has for it.
    cpu_family:  &'static str,
    sdk:         &'static str,
    /// The name meson has for the system of the device.
    subsystem:   &'static str,
    version_min: String,
    /// The simulator slice has no assembly. It only runs the UI tests under
    /// Rosetta, and the x86 assembly would need nasm on the build machine.
    assembly:    bool,
}

fn cross_for(triple: &str) -> Result<Cross> {
    Ok(match triple {
        "aarch64-apple-ios" => Cross {
            arch:        "arm64",
            cpu_family:  "aarch64",
            sdk:         "iphoneos",
            subsystem:   "ios",
            version_min: format!("-miphoneos-version-min={IOS_MINIMUM}"),
            assembly:    true,
        },
        "x86_64-apple-ios" => Cross {
            arch:        "x86_64",
            cpu_family:  "x86_64",
            sdk:         "iphonesimulator",
            subsystem:   "ios-simulator",
            version_min: format!("-mios-simulator-version-min={IOS_MINIMUM}"),
            assembly:    false,
        },
        // The simulator of an Apple Silicon Mac, for a hot build, see
        // docs/hot-reload.md in hilen. No arm64 simulator is older than iOS 14.
        "aarch64-apple-ios-sim" => Cross {
            arch:        "arm64",
            cpu_family:  "aarch64",
            sdk:         "iphonesimulator",
            subsystem:   "ios-simulator",
            version_min: "-mios-simulator-version-min=14.0".to_string(),
            assembly:    true,
        },
        "aarch64-apple-tvos" => Cross {
            arch:        "arm64",
            cpu_family:  "aarch64",
            sdk:         "appletvos",
            subsystem:   "tvos",
            version_min: format!("-mtvos-version-min={TVOS_MINIMUM}"),
            assembly:    true,
        },
        "aarch64-apple-tvos-sim" => Cross {
            arch:        "arm64",
            cpu_family:  "aarch64",
            sdk:         "appletvsimulator",
            subsystem:   "tvos-simulator",
            version_min: format!("-mtvos-simulator-version-min={TVOS_MINIMUM}"),
            assembly:    true,
        },
        _ => bail!(
            "no cross build for {triple}, only aarch64-apple-ios, aarch64-apple-ios-sim, x86_64-apple-ios, aarch64-apple-tvos and aarch64-apple-tvos-sim"
        ),
    })
}

fn main() -> Result<()> {
    let host = host_triple()?;
    let triple = std::env::args().nth(1).unwrap_or_else(|| host.clone());
    let cross = if triple == host {
        None
    } else {
        Some(cross_for(&triple)?)
    };

    let root = std::env::current_dir()?;
    let src = root.join("target/ffmpeg-src");
    // The host build keeps its old place, docs/video.md names it.
    let dist = if cross.is_some() {
        root.join(format!("target/ffmpeg-dist-{triple}"))
    } else {
        root.join("target/ffmpeg-dist")
    };
    let build = root.join(format!("target/ffmpeg-build-{triple}"));
    let src_str = src.display().to_string();
    let dist_str = dist.display().to_string();
    let build_str = build.display().to_string();

    if !src.join("configure").exists() {
        run(&format!(
            "git clone --depth=1 -b release/{VERSION} https://github.com/FFmpeg/FFmpeg {src_str}"
        ))?;
    }
    // Every target builds in a folder of its own. ffmpeg refuses that while
    // the source folder holds a build from before this script did so.
    if src.join("config.h").exists() {
        run(&format!("make -C {src_str} distclean"))?;
    }
    remove_dir(&dist)?;
    remove_dir(&build)?;
    std::fs::create_dir_all(&build)?;

    let sdk_path = match &cross {
        Some(cross) => capture(&format!("xcrun --sdk {} --show-sdk-path", cross.sdk))?,
        None => String::new(),
    };

    // dav1d first, into the same prefix, so ffmpeg finds it through
    // pkg-config and its static library lands next to the ffmpeg ones.
    let dav1d_src = root.join("target/dav1d-src");
    let dav1d_build = root.join(format!("target/dav1d-build-{triple}"));
    let dav1d_src_str = dav1d_src.display().to_string();
    let dav1d_build_str = dav1d_build.display().to_string();
    if !dav1d_src.join("meson.build").exists() {
        run(&format!(
            "git clone --depth=1 -b {DAV1D} https://code.videolan.org/videolan/dav1d.git {dav1d_src_str}"
        ))?;
    }
    remove_dir(&dav1d_build)?;
    let dav1d_cross = match &cross {
        Some(cross) => {
            let file = build.join("dav1d-cross.meson");
            std::fs::write(&file, meson_cross_file(cross, &sdk_path))?;
            let assembly = if cross.assembly { "" } else { " -Denable_asm=false" };
            format!(" --cross-file={}{assembly}", file.display())
        }
        None => String::new(),
    };
    run(&format!(
        "meson setup {dav1d_build_str} {dav1d_src_str} --prefix={dist_str} --libdir=lib --default-library=static --buildtype=release -Denable_tools=false -Denable_tests=false{dav1d_cross}"
    ))?;
    run(&format!("ninja -C {dav1d_build_str} install"))?;

    // Autodetect is off, so the system TLS is named here too. Without it the
    // archive has no https protocol.
    let hw = if cross.is_some() || cfg!(target_os = "macos") {
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

    let cross_flags = match &cross {
        Some(cross) => {
            let target = format!("-arch {} {}", cross.arch, cross.version_min);
            let assembly = if cross.assembly { "" } else { " --disable-x86asm" };
            // A cross build looks for a pkg-config with the prefix of the
            // tools, so the plain one is named.
            format!(
                " --enable-cross-compile --target-os=darwin --arch={} --cc='xcrun --sdk {} clang' --sysroot={sdk_path} --extra-cflags='{target}' --extra-ldflags='{target}' --pkg-config=pkg-config{assembly}",
                cross.arch, cross.sdk
            )
        }
        None => String::new(),
    };
    // LIBDIR, not PATH, on a cross build: a library of the host must never
    // answer for the device.
    let pkg_config = if cross.is_some() {
        "PKG_CONFIG_LIBDIR"
    } else {
        "PKG_CONFIG_PATH"
    };

    run(&format!(
        "cd {build_str} && {pkg_config}={dist_str}/lib/pkgconfig {src_str}/configure --prefix={dist_str} {flags} {hw}{cross_flags}"
    ))?;
    run(&format!("make -C {build_str} -j{} install", jobs()))?;

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

/// The compiler and the machine of the device, for the meson build of dav1d.
fn meson_cross_file(cross: &Cross, sdk_path: &str) -> String {
    let arch = cross.arch;
    let cpu_family = cross.cpu_family;
    let version_min = &cross.version_min;
    let subsystem = cross.subsystem;
    format!(
        r"[binaries]
c = ['clang', '-arch', '{arch}', '-isysroot', '{sdk_path}']
ar = 'ar'
strip = 'strip'

[built-in options]
c_args = ['{version_min}']
c_link_args = ['{version_min}']

[host_machine]
system = 'darwin'
subsystem = '{subsystem}'
cpu_family = '{cpu_family}'
cpu = '{arch}'
endian = 'little'
"
    )
}

fn remove_dir(dir: &Path) -> Result<()> {
    if dir.exists() {
        std::fs::remove_dir_all(dir)?;
    }
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
