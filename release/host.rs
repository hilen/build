#!/usr/bin/env rust

// Tells a CI job where the release files of this app go: the node that runs
// the download deployment and the folder on it. Writes `host` and `dl-dir` to
// the file named by GITHUB_OUTPUT, and prints them when there is none.

use std::fs::OpenOptions;
use std::io::Write;

use anyhow::{Context, Result};
use serde::Deserialize;
use shared::release;

#[derive(Deserialize)]
struct Deployment {
    node_hostname: String,
}

fn main() -> Result<()> {
    let r = release::read()?;
    let node: Deployment = reqwest::blocking::get(format!(
        "https://beekeeper.tailf87cbe.ts.net/api/deployments/by-name/{}",
        r.host_deployment
    ))?
    .error_for_status()
    .with_context(|| format!("beekeeper has no deployment named {}", r.host_deployment))?
    .json()?;
    let lines = format!(
        "host={}.tailf87cbe.ts.net\ndl-dir=/home/vladas/deployments/{}/data/download/{}\n",
        node.node_hostname, r.host_deployment, r.target_subdir
    );
    match std::env::var("GITHUB_OUTPUT") {
        Ok(path) => OpenOptions::new().append(true).open(path)?.write_all(lines.as_bytes())?,
        Err(_) => print!("{lines}"),
    }
    Ok(())
}
