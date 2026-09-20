#!/usr/bin/env rust

// Signs one release artifact for the engine updater. Writes `<file>.meta.json`
// with the size, sha256 and ed25519 signature, the fields updater.json embeds
// per platform. The secret is `<NAME>_UPDATE_KEY` in the env, 32 bytes hex, or
// the local key file when unset.

use anyhow::{Context, Result, bail};
use ed25519_dalek::{Signer, SigningKey};
use serde::Serialize;
use sha2::{Digest, Sha256};
use shared::release;

#[derive(Serialize)]
struct Meta {
    size: u64,
    sha256: String,
    sig: String,
}

fn main() -> Result<()> {
    let release = release::read()?;
    let files: Vec<String> = std::env::args().skip(1).collect();
    if files.is_empty() {
        bail!("usage: sign.rs <artifact> [<artifact> ...]");
    }
    let key = signing_key(&release.name)?;
    check_public_key(&key)?;
    for file in files {
        let bytes = std::fs::read(&file).with_context(|| format!("read {file}"))?;
        let meta = Meta {
            size: bytes.len() as u64,
            sha256: hex::encode(Sha256::digest(&bytes)),
            sig: hex::encode(key.sign(&bytes).to_bytes()),
        };
        let out = format!("{file}.meta.json");
        std::fs::write(&out, serde_json::to_string_pretty(&meta)?)?;
        println!("signed {file} -> {out}");
    }
    Ok(())
}

// A wrong secret would ship updates that no installed app accepts. An app that
// keeps its public key in assets/update-key.pub gets the secret checked against it.
fn check_public_key(key: &SigningKey) -> Result<()> {
    let path = "assets/update-key.pub";
    let Ok(public) = std::fs::read_to_string(path) else {
        println!("no {path}, the signing key is not checked against the app");
        return Ok(());
    };
    if hex::encode(key.verifying_key().as_bytes()) != public.trim() {
        bail!("the signing key does not match {path}, the public key embedded in the app");
    }
    Ok(())
}

fn signing_key(name: &str) -> Result<SigningKey> {
    let env_name = format!("{}_UPDATE_KEY", name.to_uppercase().replace('-', "_"));
    let hex_key = match std::env::var(&env_name) {
        Ok(k) if !k.trim().is_empty() => k,
        _ => {
            let home = std::env::var("HOME").context("HOME not set")?;
            let path = format!("{home}/.config/{name}-hilen/update-key.hex");
            std::fs::read_to_string(&path)
                .with_context(|| format!("{env_name} not set and {path} not found"))?
        }
    };
    let bytes = hex::decode(hex_key.trim()).context("update key is not hex")?;
    match SigningKey::try_from(bytes.as_slice()) {
        Ok(key) => Ok(key),
        Err(e) => bail!("update key: {e}"),
    }
}
