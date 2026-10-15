//! The `[camera]` table of hilen.toml. `usage` is the text iOS and a
//! packaged Mac app show when the app asks for the camera, the builds write
//! it into the app. An Android app gets the camera permission in its
//! manifest. With no table the app never asks, see `camera` in hilen.
//!
//! ```toml
//! [camera]
//! usage = "Takes photos of the object on the turntable."
//! ```

use anyhow::{Context, Result, ensure};
use serde::Deserialize;

/// The key of the text in an `Info.plist`.
pub const USAGE_KEY: &str = "NSCameraUsageDescription";

/// What a Mac app signed with the hardened runtime needs for the camera.
pub const ENTITLEMENT: &str = "com.apple.security.device.camera";

/// What an Android manifest needs for the camera.
pub const ANDROID_PERMISSION: &str = "android.permission.CAMERA";

#[derive(Deserialize)]
struct Hilen {
    camera: Option<Table>,
}

#[derive(Deserialize)]
struct Table {
    usage: String,
}

/// `None` for an app with no `[camera]` table.
pub fn usage_of(hilen_toml: &str) -> Result<Option<String>> {
    let hilen: Hilen = toml::from_str(hilen_toml).context("[camera] table in hilen.toml")?;
    let Some(table) = hilen.camera else {
        return Ok(None);
    };
    let usage = table.usage.trim().to_string();
    ensure!(!usage.is_empty(), "usage of [camera] in hilen.toml is empty, the system shows it to the user");
    Ok(Some(usage))
}

/// The line of a Mac `Info.plist` with the text, for inside its top
/// `<dict>`.
pub fn plist_lines(usage: &str) -> String {
    format!("  <key>{USAGE_KEY}</key><string>{}</string>\n", escape(usage))
}

/// The entitlements file of a Mac app that uses the camera.
pub fn entitlements() -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>{ENTITLEMENT}</key><true/>
</dict>
</plist>
"#
    )
}

fn escape(text: &str) -> String {
    text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

#[cfg(test)]
mod tests {
    use super::{plist_lines, usage_of};

    #[test]
    fn the_usage_text_is_read_and_escaped() {
        let toml = "project_name = \"scan\"\n[camera]\nusage = \"Photos of <the> object & more\"\n";
        let usage = usage_of(toml).unwrap().unwrap();
        assert_eq!(usage, "Photos of <the> object & more");
        assert_eq!(
            plist_lines(&usage),
            "  <key>NSCameraUsageDescription</key><string>Photos of &lt;the&gt; object &amp; more</string>\n"
        );
    }

    #[test]
    fn no_table_is_no_camera_and_an_empty_text_is_an_error() {
        assert_eq!(usage_of("project_name = \"scan\"\n").unwrap(), None);
        assert!(usage_of("[camera]\nusage = \"  \"\n").is_err());
    }
}
