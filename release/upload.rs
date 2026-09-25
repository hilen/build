#!/usr/bin/env rust

// Uploads dist/ to the download host from a dev box, the same place CI
// uploads to. The host comes from beekeeper, so a moved deployment needs no
// edit here. Prints the public urls at the end.

use anyhow::{Context, Result};
use serde::Deserialize;
use shared::release;
use shared::run::run;

#[derive(Deserialize)]
struct Deployment {
    node_hostname: String,
}

fn main() -> Result<()> {
    let r = release::read()?;
    let node: Deployment = reqwest::blocking::get(format!(
        "https://beekeeper.tailf87cbe.ts.net/api/deployments/by-name/{}",
        r.host_deployment()?
    ))?
    .error_for_status()?
    .json()?;
    let host = format!("{}.tailf87cbe.ts.net", node.node_hostname);
    let dir = format!(
        "deployments/{}/data/download/{}",
        r.host_deployment()?,
        r.target_subdir()?
    );
    run(&format!(r#"ssh {host} "mkdir -p {dir}""#))?;

    let prefix = format!("{}-{}-", r.name, r.version);
    let mut names: Vec<String> = std::fs::read_dir("dist")
        .context("dist/ missing, build a release first")?
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.starts_with(&prefix) || n == "manifest.json" || n == "updater.json")
        .collect();
    names.sort();
    for name in &names {
        run(&format!("scp dist/{name} {host}:{dir}/"))?;
    }
    for name in &names {
        if !name.ends_with(".meta.json") {
            println!("{}/{name}", r.download_url()?);
        }
    }
    Ok(())
}
