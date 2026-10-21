# The `[local_network]` table of hilen.toml, for an app that finds devices on
# the local network with `discovery::ServiceBrowser` of hilen. It holds the
# service types, like `services = ["_turnscan._tcp"]`, and the text the system
# shows, like `usage = "Turnscan finds its turntable boards on your Wi-Fi."`.
#
# An iPhone and an Apple TV let an app browse only for the types in
# `NSBonjourServices` of its Info.plist, and ask the user with the text of
# `NSLocalNetworkUsageDescription` the first time. Android hears multicast on
# Wi-Fi only while the app holds a multicast lock, and that needs the
# `CHANGE_WIFI_MULTICAST_STATE` permission in the manifest.

import subprocess
from typing import Final

import msgspec

from shared.util import bail

# The type the inspect server of hilen announces.
INSPECT_SERVICE: Final = "_hilen-inspect._tcp"
_INSPECT_USAGE: Final = "The developer tools find this app on the local network."

# The line the Android manifest needs for the multicast lock.
MULTICAST_PERMISSION: Final = (
    '<uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE"/>'
)
_SERVICE_PARTS: Final = 2


class LocalNetwork(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    # The service types the app browses for, like `_turnscan._tcp`.
    services: tuple[str, ...]
    # Why the app wants the local network, the system shows it to the user.
    usage: str


# `_name._tcp` or `_name._udp`, with no domain.
def _is_service_type(text: str) -> bool:
    parts = text.split(".")
    return (
        len(parts) == _SERVICE_PARTS
        and parts[1] in {"_tcp", "_udp"}
        and len(parts[0]) > 1
        and parts[0].startswith("_")
    )


def check(network: LocalNetwork) -> LocalNetwork:
    if not network.services:
        bail("services of [local_network] in hilen.toml names no service type")
    for service in network.services:
        if not _is_service_type(service):
            bail(
                f'"{service}" in services of [local_network] in hilen.toml is no service type, '
                'write it like "_turnscan._tcp"'
            )
    if not network.usage.strip():
        bail("usage of [local_network] in hilen.toml is empty, the system shows it to the user")
    return network


# The 2 keys of an Info.plist, the service types and the text, for the table of
# the app and for the inspect server when the build carries it. None when the
# app has neither.
def plist_keys(network: LocalNetwork | None, *, inspect: bool) -> tuple[list[str], str] | None:
    services = [] if network is None else list(network.services)
    if inspect and INSPECT_SERVICE not in services:
        services.append(INSPECT_SERVICE)
    if not services:
        return None
    return services, _INSPECT_USAGE if network is None else network.usage


# plutil takes the values as arguments, so the text needs no quoting.
def write_plist(plist: str, network: LocalNetwork | None, *, inspect: bool):
    keys = plist_keys(network, inspect=inspect)
    if keys is None:
        return
    services, usage = keys
    for args in (
        ["-replace", "NSLocalNetworkUsageDescription", "-string", usage, plist],
        ["-replace", "NSBonjourServices", "-json", msgspec.json.encode(services).decode(), plist],
    ):
        print(f"plutil {' '.join(args)}", flush=True)
        if subprocess.run(["plutil", *args], check=False).returncode != 0:
            bail(f"plutil did not write {plist}")
