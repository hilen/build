#!/usr/bin/env rust

// The Linux release, built in docker so the output is the same on a dev box
// and on a runner. One arch per run, `--arch x64|aarch64`, default is the
// host's. Outputs in dist/:
//   <name>-<v>-linux-<arch>.deb        first install, updates through apt
//   <name>-<v>-linux-<arch>.AppImage   signed, self updates in place
//   <name>-<v>-linux-<triple-arch>     the bare binary, signed for the manifest

mod docker;

use anyhow::{Result, bail};

const STAGE: &str = "target/linux-stage";
use shared::inspect;
use shared::release::{self, Release};

fn main() -> Result<()> {
    inspect::mark_release();
    let r = release::read()?;
    let arch = std::env::args()
        .skip(1)
        .find_map(|a| a.strip_prefix("--arch=").map(str::to_string))
        .unwrap_or_else(host_arch);
    let (platform, rust_arch) = match arch.as_str() {
        "x64" => ("linux/amd64", "x86_64"),
        "aarch64" => ("linux/arm64", "aarch64"),
        other => bail!("unknown arch {other}, use x64 or aarch64"),
    };
    std::fs::create_dir_all("dist")?;
    // target/release-linux is a docker volume, so everything the host writes
    // for the container or reads back lives in a sibling dir.
    std::fs::create_dir_all(STAGE)?;
    write_desktop_file(&r)?;

    let image = format!("{}-linux-builder", r.name);
    docker::build_image(&image, "Dockerfile.linux", platform)?;
    let script = format!(
        r#"set -euo pipefail
cargo build --locked --release -p {name} --bin {bin}
BIN=target/release-linux/release/{bin}
OUT={stage}/out
rm -rf $OUT /tmp/out && mkdir -p $OUT /tmp/out
cargo deb -p {name} --no-build --no-strip -o $OUT/{name}.deb
cd /tmp/out
linuxdeploy --appdir AppDir -e /work/apps/app/$BIN -d /work/apps/app/{stage}/{name}.desktop -i /work/apps/app/{stage}/{name}.png --output appimage
cd /work/apps/app
cp /tmp/out/{name}-*.AppImage $OUT/{name}.AppImage
cp $BIN $OUT/{name}"#,
        name = r.name,
        bin = r.bin,
        stage = STAGE
    );
    docker::run_in(&r.name, &image, platform, "release-linux", "linux-stage", &script)?;

    let out = format!("{STAGE}/out");
    // The .deb and the AppImage pack this same binary.
    inspect::refuse(&format!("{out}/{}", r.name))?;
    let deb = format!("dist/{}", r.artifact(&format!("linux-{arch}.deb")));
    let appimage = format!("dist/{}", r.artifact(&format!("linux-{arch}.AppImage")));
    let bare = format!("dist/{}", r.artifact(&format!("linux-{rust_arch}")));
    std::fs::copy(format!("{out}/{}.deb", r.name), &deb)?;
    std::fs::copy(format!("{out}/{}.AppImage", r.name), &appimage)?;
    std::fs::copy(format!("{out}/{}", r.name), &bare)?;
    r.sign(&[&bare, &appimage])?;
    for f in [&deb, &appimage, &bare] {
        println!("built {f}");
    }
    Ok(())
}

fn host_arch() -> String {
    if std::env::consts::ARCH == "aarch64" {
        "aarch64".to_string()
    } else {
        "x64".to_string()
    }
}

// linuxdeploy wants the icon file named after the desktop entry's Icon.
fn write_desktop_file(r: &Release) -> Result<()> {
    std::fs::copy("assets/icon.png", format!("{STAGE}/{}.png", r.name))?;
    std::fs::write(
        format!("{STAGE}/{}.desktop", r.name),
        format!(
            r#"[Desktop Entry]
Type=Application
Name={name}
Exec={bin}
Icon={name}
Categories=Development;
Terminal=false
"#,
            name = r.name,
            bin = r.bin
        ),
    )?;
    Ok(())
}
