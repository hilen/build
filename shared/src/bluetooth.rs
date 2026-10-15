//! The `[bluetooth]` table of hilen.toml, for an app on the `bluetooth`
//! feature of hilen. macOS shows `usage` when it asks the user for
//! Bluetooth, and it ends an app bundle that uses Bluetooth with no such
//! text. `hilen-mobile` writes the same table into the phone projects.

use anyhow::{Context, Result, ensure};
use serde::Deserialize;

#[derive(Deserialize)]
struct Hilen {
    bluetooth: Option<Table>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Table {
    usage: String,
}

/// `None` for an app with no `[bluetooth]` table.
pub fn usage_of(hilen_toml: &str) -> Result<Option<String>> {
    let hilen: Hilen = toml::from_str(hilen_toml).context("[bluetooth] table in hilen.toml")?;
    let Some(table) = hilen.bluetooth else {
        return Ok(None);
    };
    ensure!(
        !table.usage.trim().is_empty(),
        "usage of [bluetooth] in hilen.toml is empty, macOS shows it when it asks the user for Bluetooth"
    );
    Ok(Some(table.usage))
}

/// The line of a Mac `Info.plist` with the text, for inside its top `<dict>`.
pub fn plist_lines(usage: &str) -> String {
    let usage = usage
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;");
    format!("  <key>NSBluetoothAlwaysUsageDescription</key><string>{usage}</string>\n")
}

#[cfg(test)]
mod test {
    use super::{plist_lines, usage_of};

    #[test]
    fn no_table_no_text() {
        assert_eq!(usage_of("project_name = \"turnscan\"").unwrap(), None);
    }

    #[test]
    fn the_text_comes_from_the_table() {
        let toml = "project_name = \"turnscan\"\n[bluetooth]\nusage = \"Drives the turntable.\"\n";
        assert_eq!(usage_of(toml).unwrap().as_deref(), Some("Drives the turntable."));
    }

    #[test]
    fn a_wrong_table_is_an_error() {
        for toml in [
            "[bluetooth]",
            "[bluetooth]\nusage = \" \"",
            "[bluetooth]\nusage = \"x\"\nscan = true",
        ] {
            assert!(usage_of(toml).is_err(), "{toml}");
        }
    }

    #[test]
    fn the_plist_line_escapes_the_text() {
        assert_eq!(
            plist_lines("Scans <boards> & lights"),
            "  <key>NSBluetoothAlwaysUsageDescription</key><string>Scans &lt;boards&gt; &amp; lights</string>\n"
        );
    }
}
