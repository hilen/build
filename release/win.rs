#!/usr/bin/env rust

// The Windows release, cross built in docker with cargo-xwin and packed by
// NSIS. `--arch x64|arm64`, default both. Outputs in dist/:
//   <name>-<v>-windows-<arch>-setup.exe   first install
//   <name>-<v>-windows-<arch>.exe         the bare exe the updater swaps in

mod docker;

use anyhow::{Result, bail};
use shared::{inspect, release};

const TARGETS: [(&str, &str); 2] = [
    ("x64", "x86_64-pc-windows-msvc"),
    ("arm64", "aarch64-pc-windows-msvc"),
];

fn main() -> Result<()> {
    inspect::mark_release();
    let r = release::read()?;
    let only = std::env::args()
        .skip(1)
        .find_map(|a| a.strip_prefix("--arch=").map(str::to_string));
    let targets: Vec<(&str, &str)> = TARGETS
        .iter()
        .copied()
        .filter(|(arch, _)| only.as_deref().is_none_or(|o| o == *arch))
        .collect();
    if targets.is_empty() {
        bail!("unknown arch, use x64 or arm64");
    }
    std::fs::create_dir_all("dist")?;

    // target/release-win is a docker volume, so everything the host reads
    // back is staged into a sibling dir like the linux lane does.
    let stage = "target/win-stage/out";
    std::fs::create_dir_all(stage)?;

    let image = format!("{}-win-builder", r.name);
    let platform = "linux/amd64";
    docker::build_image(&image, "Dockerfile.windows", platform)?;
    let mut script = String::from("set -euo pipefail\nrustup component add rust-src\n");
    for (arch, triple) in &targets {
        script.push_str(&format!(
            r#"rustup target add {triple}
cargo xwin build --locked --release -p {name} --bin {bin} --target {triple}
makensis -DNAME={name} -DVERSION={version} -DEXE=/work/apps/app/target/release-win/{triple}/release/{bin}.exe -DICON=/work/apps/app/assets/icon.ico -DOUTPUT=/work/apps/app/{stage}/{name}-{arch}-setup.exe build/release/installer.nsi
cp /work/apps/app/target/release-win/{triple}/release/{bin}.exe /work/apps/app/{stage}/{name}-{arch}.exe
"#,
            name = r.name,
            bin = r.bin,
            version = r.version
        ));
    }
    docker::run_in(&r.name, &image, platform, "release-win", "win-stage", &script)?;

    // The setup exe packs this same exe, so a clean exe means a clean setup.
    for (arch, _) in &targets {
        inspect::refuse(&format!("{stage}/{}-{arch}.exe", r.name))?;
    }
    for (arch, _) in &targets {
        let setup = format!("dist/{}", r.artifact(&format!("windows-{arch}-setup.exe")));
        let bare = format!("dist/{}", r.artifact(&format!("windows-{arch}.exe")));
        std::fs::copy(format!("{stage}/{}-{arch}-setup.exe", r.name), &setup)?;
        std::fs::copy(format!("{stage}/{}-{arch}.exe", r.name), &bare)?;
        r.sign(&[&bare])?;
        println!("built {setup}");
        println!("built {bare}");
    }
    Ok(())
}
