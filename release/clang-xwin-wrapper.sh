#!/bin/bash
# cc-rs falls back to gcc-mode clang for .S (GNU assembly) files even on
# MSVC targets, but cargo-xwin's CFLAGS_<target> use clang-cl's MSVC-style
# `/imsvc <PATH>` pairs which gcc-mode clang doesn't understand. Translate
# those pairs to plain `-I <PATH>` so the same CFLAGS work in both modes.
#
# Installed as `/usr/local/bin/clang` so it shadows `/usr/bin/clang` on PATH.
#
# cargo-xwin makes its `clang-cl` a symlink to the first clang on PATH, which is
# this file. A plain exec of clang would drop cl mode, and an MSVC flag such as
# `/FI<file>` is then read as an input file. aws-lc-sys fails on exactly that.
# So a call under the name clang-cl keeps cl mode and its arguments as they are.
if [ "$(basename "$0")" = "clang-cl" ]; then
  exec /usr/lib/llvm-14/bin/clang --driver-mode=cl "$@"
fi

args=()
while [ $# -gt 0 ]; do
  case "$1" in
    /imsvc)
      shift
      args+=("-I" "$1")
      ;;
    *)
      args+=("$1")
      ;;
  esac
  shift
done
exec /usr/lib/llvm-14/bin/clang "${args[@]}"
