#!/usr/bin/env rust

// Prints the name of the upload grant of this app, `<deployment>-<folder>`,
// like `get-flixen`. door.sh sends the release files to beekeeper under that
// name, and beekeeper knows which folder of which deployment it stands for.

use anyhow::Result;
use shared::release;

fn main() -> Result<()> {
    let r = release::read()?;
    println!("{}-{}", r.host_deployment, r.target_subdir.replace('/', "-"));
    Ok(())
}
