//! Keeps the hilen inspect server out of every shipped build. The server lets
//! anyone on the network read and drive the app. The engine build script stops
//! a build that has the `inspect` feature while HILEN_RELEASE is set, and
//! `refuse` checks the built file itself, which also catches a build that never
//! set the mark.

use std::process::{Command, Output};

use anyhow::{Result, bail};

/// The engine build script refuses the `inspect` feature while this is set.
pub const RELEASE_ENV: &str = "HILEN_RELEASE";

/// `MARKER` of hilen/src/inspect/mod.rs in two pieces, so no copy of this
/// code ever matches its own scan.
const MARKER_PARTS: [&str; 2] = ["hilen-inspect-", "server-compiled-in"];

/// Marks this process and every command it starts as a shipped build. The
/// wrapper with-secrets.sh sets the same mark, this covers a run without it.
pub fn mark_release() {
    unsafe {
        std::env::set_var(RELEASE_ENV, "1");
    }
}

pub fn is_release() -> bool {
    std::env::var(RELEASE_ENV).is_ok_and(|mark| !mark.is_empty())
}

fn scan(path: &str) -> Result<Output> {
    let marker = MARKER_PARTS.concat();
    Ok(Command::new("grep")
        .args(["-r", "-l", "-a", "-F", "--", &marker, path])
        .output()?)
}

/// Whether the file at `path` carries the inspect server. An iOS app with it
/// needs the local network keys in its `Info.plist`.
pub fn has_server(path: &str) -> Result<bool> {
    let out = scan(path)?;
    match out.status.code() {
        Some(0) => Ok(true),
        Some(1) => Ok(false),
        _ => bail!(
            "could not scan {path} for the inspect server: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ),
    }
}

/// Fails when the file at `path`, or any file under it for a folder, carries
/// the inspect server. Call it on the built binary before anything is signed,
/// packed or copied to dist.
pub fn refuse(path: &str) -> Result<()> {
    let out = scan(path)?;
    match out.status.code() {
        Some(1) => {
            println!("{path} has no inspect server");
            Ok(())
        }
        Some(0) => bail!(
            "{} carries the hilen inspect server, refusing to ship it. Build without the `inspect` feature, see docs/inspect.md in the hilen repo.",
            String::from_utf8_lossy(&out.stdout).trim()
        ),
        _ => bail!(
            "could not scan {path} for the inspect server: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ),
    }
}
