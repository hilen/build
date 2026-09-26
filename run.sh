#!/bin/sh
# Build and run the release binary. Plain sh so it works on a fresh WSL before
# the rust interpreter exists.
#
# The Sentry DSN comes from Infisical so the bug report button works like a
# shipped build. The app's Makefile passes its project as INFISICAL_PROJECT.
# When that is unset, or Infisical is missing or not logged in, it falls back
# to a plain build and run. Then only the bug report button is dead,
# everything else works.
set -eu

PROJECT="${INFISICAL_PROJECT:-}"
# An app's Makefile can pass cargo features for its dev run in RUN_FEATURES,
# like a `dev` feature that turns on the hilen inspect server.
FEATURES="${RUN_FEATURES:+--features $RUN_FEATURES}"
CONFIG="$HOME/.infisical/infisical-config.json"

# Only WSL gets the automatic dependency install. A mac or a normal Linux box
# is set up by hand, and setup.sh would fail there without apt, dnf or pacman.
if [ -n "${WSL_DISTRO_NAME:-}" ]; then
	sh build/setup.sh
fi

# Probe the login state from the config file, not by calling infisical. A not
# logged in `infisical export` launches an interactive login and still exits 0,
# so it cannot be used to detect the state. The config records the logged in
# email, empty when there is no session.
if [ -n "$PROJECT" ] \
	&& command -v infisical >/dev/null 2>&1 \
	&& [ -f "$CONFIG" ] \
	&& grep -q '"loggedInUserEmail":"[^"]' "$CONFIG"; then
	infisical run --projectId "$PROJECT" --env prod -- cargo build --release $FEATURES
	infisical run --projectId "$PROJECT" --env prod -- cargo run --release $FEATURES
else
	echo "infisical not available or not logged in, running without the Sentry setup"
	echo "the bug report button will do nothing, everything else works"
	cargo build --release $FEATURES
	cargo run --release $FEATURES
fi
