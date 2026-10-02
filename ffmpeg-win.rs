#!/usr/bin/env rust

// Builds the static ffmpeg archive for x86_64 Windows, the twin of ffmpeg.rs
// for the one target that is not built on its own host. It cross builds in
// docker with clang in cl mode and the MSVC SDK from xwin, the same kind of
// build the Windows release of an app is, so the archive links there. The
// result in dist/ goes to a release of this repo like the others, see
// docs/video.md in hilen. The versions have to match ffmpeg.rs.

use anyhow::Result;
use shared::run::run;

const VERSION: &str = "9.0";
const DAV1D: &str = "1.5.4";
const ZLIB: &str = "1.3.1";

fn main() -> Result<()> {
    std::fs::create_dir_all("dist")?;
    let out = std::env::current_dir()?.join("dist");
    run("docker build -t hilen-ffmpeg-win build/ffmpeg-win")?;
    run(&format!(
        r#"docker run --rm -v "{}:/out" hilen-ffmpeg-win /opt/build.sh {VERSION} {DAV1D} {ZLIB}"#,
        out.display()
    ))?;
    println!("dist/ffmpeg-{VERSION}-x86_64-pc-windows-msvc.tar.gz");
    Ok(())
}
