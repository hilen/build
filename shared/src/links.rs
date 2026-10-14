//! The url scheme of the `[links]` table of hilen.toml, which the desktop
//! packaging registers with the system. A click on a link of the scheme,
//! like `shopping://invite/x7k2`, then starts the app with the link, and the
//! engine gives it to the app, see `system::Links` in hilen. The domains of
//! the table are for the phones, `hilen-mobile` writes them.
//!
//! Not set, the scheme is the project_name in lower case with `-` for `_`,
//! the same rule as `link_scheme!` of the engine and as `hilen-mobile`.

use anyhow::{Context, Result, ensure};

/// `None` for an app with no `[links]` table.
pub fn scheme_of(hilen_toml: &str) -> Result<Option<String>> {
    let value: serde_json::Value = toml::from_str(hilen_toml).context("hilen.toml")?;
    let Some(links) = value.get("links") else {
        return Ok(None);
    };
    let scheme = match links.get("scheme") {
        Some(scheme) => scheme
            .as_str()
            .context("scheme of [links] in hilen.toml is not a text")?
            .to_string(),
        None => value
            .get("project_name")
            .and_then(serde_json::Value::as_str)
            .context("project_name not found in hilen.toml")?
            .to_lowercase()
            .replace('_', "-"),
    };
    let mut chars = scheme.chars();
    ensure!(
        chars.next().is_some_and(|c| c.is_ascii_lowercase())
            && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '+' | '-' | '.')),
        "the link scheme {scheme:?} in hilen.toml must start with a small letter and have only small letters, digits, +, - and ."
    );
    ensure!(
        !matches!(scheme.as_str(), "http" | "https" | "file"),
        "the link scheme {scheme:?} in hilen.toml belongs to the system"
    );
    Ok(Some(scheme))
}

/// The lines of a Mac `Info.plist` that register the scheme, for inside its
/// top `<dict>`.
pub fn plist_lines(scheme: &str, bundle_id: &str) -> String {
    format!(
        "  <key>CFBundleURLTypes</key>\n  <array>\n    <dict>\n      <key>CFBundleURLName</key><string>{bundle_id}</string>\n      <key>CFBundleURLSchemes</key><array><string>{scheme}</string></array>\n    </dict>\n  </array>\n"
    )
}

/// The `Exec` and `MimeType` lines of a Linux desktop entry. With a scheme
/// the program gets the link as its argument, `%u`, and the entry says it
/// opens the links of the scheme.
pub fn desktop_lines(bin: &str, scheme: Option<&str>) -> String {
    match scheme {
        Some(scheme) => format!("Exec={bin} %u\nMimeType=x-scheme-handler/{scheme};\n"),
        None => format!("Exec={bin}\n"),
    }
}

#[cfg(test)]
mod test {
    use super::{desktop_lines, plist_lines, scheme_of};

    #[test]
    fn no_table_no_scheme() {
        assert_eq!(scheme_of("project_name = \"shopping\"").unwrap(), None);
    }

    #[test]
    fn the_scheme_is_the_project_name_unless_the_table_names_one() {
        let toml = "project_name = \"My_Shop\"\n[links]\ndomains = [\"shop.example.com\"]\n";
        assert_eq!(scheme_of(toml).unwrap().as_deref(), Some("my-shop"));
        let toml = "project_name = \"shop\"\n[links]\nscheme = \"shop-app\"\n";
        assert_eq!(scheme_of(toml).unwrap().as_deref(), Some("shop-app"));
    }

    #[test]
    fn a_wrong_scheme_is_an_error() {
        for scheme in ["Shop", "1shop", "shop app", "https", ""] {
            let toml = format!("project_name = \"shop\"\n[links]\nscheme = \"{scheme}\"\n");
            assert!(scheme_of(&toml).is_err(), "{scheme:?}");
        }
    }

    #[test]
    fn the_plist_lines_name_the_scheme() {
        let lines = plist_lines("shopping", "vladas.shopping");
        assert!(lines.contains("<key>CFBundleURLSchemes</key><array><string>shopping</string></array>"));
        assert!(lines.contains("<string>vladas.shopping</string>"));
    }

    #[test]
    fn the_desktop_entry_takes_the_link_as_its_argument() {
        assert_eq!(
            desktop_lines("shopping", Some("shopping")),
            "Exec=shopping %u\nMimeType=x-scheme-handler/shopping;\n"
        );
        assert_eq!(desktop_lines("shopping", None), "Exec=shopping\n");
    }
}
