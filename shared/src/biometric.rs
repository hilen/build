//! The `[biometric]` table of hilen.toml, for an app on the `biometric`
//! feature of hilen. `usage` is the text an iPhone or an iPad shows when the
//! app asks for Face ID, the iOS build writes it into the app. Touch ID and
//! a Mac need no text.
//!
//! ```toml
//! [biometric]
//! usage = "Face ID confirms each payment you send."
//! ```

use anyhow::{Context, Result, ensure};
use serde::Deserialize;

/// The key of the text in an `Info.plist`.
pub const USAGE_KEY: &str = "NSFaceIDUsageDescription";

#[derive(Deserialize)]
struct Hilen {
    biometric: Option<Table>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Table {
    usage: String,
}

/// `None` for an app with no `[biometric]` table.
pub fn usage_of(hilen_toml: &str) -> Result<Option<String>> {
    let hilen: Hilen = toml::from_str(hilen_toml).context("[biometric] table in hilen.toml")?;
    let Some(table) = hilen.biometric else {
        return Ok(None);
    };
    let usage = table.usage.trim().to_string();
    ensure!(
        !usage.is_empty(),
        "usage of [biometric] in hilen.toml is empty, iOS shows it when it asks the user for Face ID"
    );
    Ok(Some(usage))
}

#[cfg(test)]
mod tests {
    use super::usage_of;

    #[test]
    fn the_text_comes_from_the_table() {
        let toml = "project_name = \"wallet\"\n[biometric]\nusage = \" Face ID confirms each payment. \"\n";
        assert_eq!(usage_of(toml).unwrap().as_deref(), Some("Face ID confirms each payment."));
    }

    #[test]
    fn no_table_no_text() {
        assert_eq!(usage_of("project_name = \"wallet\"\n").unwrap(), None);
    }

    #[test]
    fn a_wrong_table_is_an_error() {
        for toml in ["[biometric]\n", "[biometric]\nusage = \"  \"\n", "[biometric]\nusage = \"a\"\nother = 1\n"] {
            assert!(usage_of(toml).is_err(), "{toml}");
        }
    }
}
