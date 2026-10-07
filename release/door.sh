#!/usr/bin/env bash
# Sends release files to the upload door of beekeeper and reads them back,
# with the token of this app's upload grant. Run it from the app root.
#
#   door.sh put <file> [<file> ...]    upload files into the download folder
#   door.sh list                       the names in the download folder
#   door.sh get <name> <folder>        fetch one file into a local folder
#
# UPLOAD_TOKEN is in the Infisical project of the app, so call this through
# with-secrets.sh. The door is on the home LAN, UPLOAD_DOOR names another
# address. A CI runner has no login on any node, the door is its only way in.
set -euo pipefail

: "${UPLOAD_TOKEN:?UPLOAD_TOKEN is not set, it lives in the Infisical project of the app}"

here="$(cd "$(dirname "$0")" && pwd)"
# release::read prints the cargo command it runs first, the name is the last line.
grant="$(rust "$here/grant.rs" | tail -n 1)"
url="${UPLOAD_DOOR:-http://192.168.0.101:8191}/upload/$grant"

# The token reaches curl in a config on stdin, so it never shows in a
# process list.
call() {
    printf 'header = "Authorization: Bearer %s"\n' "$UPLOAD_TOKEN" \
        | curl --silent --show-error --fail-with-body --config - "$@"
}

case "${1-}" in
    put)
        shift
        for file in "$@"; do
            name="$(basename "$file")"
            call --upload-file "$file" "$url/$name" > /dev/null
            echo "uploaded $name"
        done
        ;;
    list)
        call "$url"
        ;;
    get)
        call --output "$3/$2" "$url/$2"
        ;;
    *)
        echo "usage: door.sh put <file>... | list | get <name> <folder>" >&2
        exit 2
        ;;
esac
