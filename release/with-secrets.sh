#!/usr/bin/env bash
# Runs a command with the prod secrets of one or more Infisical projects in
# its env, over the runner's machine identity. Copied from the karkas
# infisical_run.sh, the mac runner keeps infisical in the nix profile.
#
#   with-secrets.sh <projectId> [<projectId> ...] -- <cmd> [<arg> ...]
set -euo pipefail

export PATH="/run/current-system/sw/bin:$HOME/.nix-profile/bin:$PATH"
INFISICAL_URL="${INFISICAL_URL:-https://infisical.vladas.xyz}"

projects=()
while [ "${1-}" != "--" ]; do
    if [ "$#" -eq 0 ]; then
        echo "with-secrets.sh: missing '--' separator" >&2
        exit 2
    fi
    projects+=("$1")
    shift
done
shift

if [ -n "${CREDENTIALS_DIRECTORY:-}" ] && [ -f "$CREDENTIALS_DIRECTORY/infisical" ]; then
    . "$CREDENTIALS_DIRECTORY/infisical"
else
    . "$HOME/.infisical/ci_credentials"
fi

TOKEN=$(curl -sSf -X POST "$INFISICAL_URL/api/v1/auth/universal-auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"clientId\":\"$INFISICAL_MACHINE_IDENTITY_CLIENT_ID\",\"clientSecret\":\"$INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET\"}" \
    | jq -er .accessToken)

cmd=("$@")
for ((i=${#projects[@]}-1; i>=0; i--)); do
    cmd=(infisical run --token "$TOKEN" --domain "$INFISICAL_URL/api" --projectId "${projects[$i]}" --env prod -- "${cmd[@]}")
done
exec "${cmd[@]}"
