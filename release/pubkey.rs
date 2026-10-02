#!/usr/bin/env rust

// Prints the public half of the app's update key as hex, the value that goes
// into assets/update-key.pub and that sign.rs checks the signing key against.
// The secret comes from the same place as in sign.rs, `<NAME>_UPDATE_KEY` in
// the env or ~/.config/<name>-hilen/update-key.hex.

use anyhow::{Context, Result, bail};
use ed25519_dalek::SigningKey;
use shared::release;

fn main() -> Result<()> {
    let name = release::read()?.name;
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
        Ok(key) => println!("{}", hex::encode(key.verifying_key().as_bytes())),
        Err(e) => bail!("update key: {e}"),
    }
    Ok(())
}
