//! The `[local_network]` table of hilen.toml, for an app that finds devices
//! on the local network with `discovery::ServiceBrowser` of hilen:
//!
//! ```toml
//! [local_network]
//! services = ["_turnscan._tcp"]
//! usage = "Turnscan finds its turntable boards on your Wi-Fi."
//! ```
//!
//! An iPhone and an Apple TV let an app browse only for the types in
//! `NSBonjourServices` of its Info.plist, and ask the user with the text of
//! `NSLocalNetworkUsageDescription` the first time. Android hears multicast
//! on Wi-Fi only while the app holds a multicast lock, and that needs the
//! `CHANGE_WIFI_MULTICAST_STATE` permission in the manifest.

use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::Value;

/// The type the inspect server of hilen announces.
pub const INSPECT_SERVICE: &str = "_hilen-inspect._tcp";
const INSPECT_USAGE: &str = "The developer tools find this app on the local network.";

/// The line the Android manifest needs for the multicast lock.
pub const MULTICAST_PERMISSION: &str =
    "<uses-permission android:name=\"android.permission.CHANGE_WIFI_MULTICAST_STATE\"/>";

#[derive(Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalNetwork {
    /// The service types the app browses for, like `_turnscan._tcp`.
    pub services: Vec<String>,
    /// Why the app wants the local network, the system shows it to the user.
    pub usage:    String,
}

impl LocalNetwork {
    /// `None` for an app with no table.
    pub fn read(hilen_toml: &Value) -> Result<Option<Self>> {
        let Some(table) = hilen_toml.get("local_network") else {
            return Ok(None);
        };
        let network: Self =
            serde_json::from_value(table.clone()).context("[local_network] table in hilen.toml")?;
        ensure!(
            !network.services.is_empty(),
            "services of [local_network] in hilen.toml names no service type"
        );
        for service in &network.services {
            ensure!(
                is_service_type(service),
                "{service:?} in services of [local_network] in hilen.toml is no service type, write it like \"_turnscan._tcp\""
            );
        }
        ensure!(
            !network.usage.trim().is_empty(),
            "usage of [local_network] in hilen.toml is empty, the system shows it to the user"
        );
        Ok(Some(network))
    }
}

/// `_name._tcp` or `_name._udp`, with no domain.
fn is_service_type(text: &str) -> bool {
    matches!(
        text.split('.').collect::<Vec<_>>().as_slice(),
        [name, "_tcp" | "_udp"] if name.len() > 1 && name.starts_with('_')
    )
}

/// The 2 keys of an Info.plist, the service types and the text, for the
/// table of the app and for the inspect server when the build carries it.
/// `None` when the app has neither.
pub fn plist_keys(network: Option<&LocalNetwork>, inspect: bool) -> Option<(Vec<String>, String)> {
    let mut services = network.map(|network| network.services.clone()).unwrap_or_default();
    if inspect && !services.iter().any(|service| service == INSPECT_SERVICE) {
        services.push(INSPECT_SERVICE.to_string());
    }
    if services.is_empty() {
        return None;
    }
    let usage = network.map_or_else(|| INSPECT_USAGE.to_string(), |network| network.usage.clone());
    Some((services, usage))
}

/// Writes the 2 keys into the Info.plist at `plist`. `plutil` takes the
/// values as arguments, so the text needs no quoting.
pub fn write_plist(plist: &str, network: Option<&LocalNetwork>, inspect: bool) -> Result<()> {
    let Some((services, usage)) = plist_keys(network, inspect) else {
        return Ok(());
    };
    let services = serde_json::to_string(&services)?;
    for args in [
        ["-replace", "NSLocalNetworkUsageDescription", "-string", usage.as_str(), plist],
        ["-replace", "NSBonjourServices", "-json", services.as_str(), plist],
    ] {
        println!("plutil {}", args.join(" "));
        let status = std::process::Command::new("plutil").args(args).status()?;
        ensure!(status.success(), "plutil did not write {plist}");
    }
    Ok(())
}

#[cfg(test)]
mod test {
    use super::{INSPECT_SERVICE, LocalNetwork, plist_keys};

    fn read(toml: &str) -> anyhow::Result<Option<LocalNetwork>> {
        LocalNetwork::read(&toml::from_str(toml)?)
    }

    #[test]
    fn no_table_no_network() {
        assert_eq!(read("project_name = \"turnscan\"").unwrap(), None);
        assert_eq!(plist_keys(None, false), None);
    }

    #[test]
    fn the_table_is_read_and_checked() {
        let network = read("[local_network]\nservices = [\"_turnscan._tcp\"]\nusage = \"Finds the boards.\"\n")
            .unwrap()
            .unwrap();
        assert_eq!(network.services, ["_turnscan._tcp"]);
        assert_eq!(network.usage, "Finds the boards.");

        for wrong in [
            "[local_network]\nservices = []\nusage = \"x\"\n",
            "[local_network]\nservices = [\"turnscan\"]\nusage = \"x\"\n",
            "[local_network]\nservices = [\"_turnscan._tcp.local.\"]\nusage = \"x\"\n",
            "[local_network]\nservices = [\"_turnscan._tcp\"]\nusage = \" \"\n",
            "[local_network]\nservices = [\"_turnscan._tcp\"]\n",
            "[local_network]\nservices = [\"_turnscan._tcp\"]\nusage = \"x\"\nother = 1\n",
        ] {
            assert!(read(wrong).is_err(), "{wrong} was taken");
        }
    }

    #[test]
    fn the_inspect_service_joins_the_ones_of_the_app() {
        let network = LocalNetwork {
            services: vec!["_turnscan._tcp".into()],
            usage:    "Finds the boards.".into(),
        };
        let (services, usage) = plist_keys(Some(&network), true).unwrap();
        assert_eq!(services, ["_turnscan._tcp", INSPECT_SERVICE]);
        assert_eq!(usage, "Finds the boards.");

        let (services, _) = plist_keys(Some(&network), false).unwrap();
        assert_eq!(services, ["_turnscan._tcp"]);

        let (services, usage) = plist_keys(None, true).unwrap();
        assert_eq!(services, [INSPECT_SERVICE]);
        assert!(usage.contains("developer tools"));
    }
}
